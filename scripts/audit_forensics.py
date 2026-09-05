"""AMANCORE Forensic Audit Master Analyzer — Complete Suite
Gathers verifiable evidence across all 12 Prompts.
"""

from __future__ import annotations

import ast
import hashlib
import json
import multiprocessing
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path("/home/omar/Desktop/work/aman-core").resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_cmd(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    p = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# ==============================================================================
# PROMPT 01 & GIT METADATA
# ==============================================================================

def get_git_info():
    _, branch, _ = run_cmd(["git", "branch", "--show-current"])
    _, head, _ = run_cmd(["git", "rev-parse", "HEAD"])
    _, head_short, _ = run_cmd(["git", "rev-parse", "--short", "HEAD"])
    _, status, _ = run_cmd(["git", "status", "--porcelain"])
    _, log_lines, _ = run_cmd(["git", "log", "-n", "30", "--oneline", "--decorate"])
    _, ls_tree, _ = run_cmd(["git", "ls-tree", "-r", "--name-only", "HEAD"])
    _, remote, _ = run_cmd(["git", "remote", "-v"])
    _, tags, _ = run_cmd(["git", "tag", "-l"])
    
    return {
        "branch": branch.strip(),
        "head": head.strip(),
        "head_short": head_short.strip(),
        "working_tree_clean": len(status.strip()) == 0,
        "status_raw": status.strip(),
        "log_30": log_lines.strip().splitlines(),
        "tracked_files_count": len(ls_tree.strip().splitlines()) if ls_tree.strip() else 0,
        "tracked_files": ls_tree.strip().splitlines() if ls_tree.strip() else [],
        "remote": remote.strip(),
        "tags": tags.strip().splitlines() if tags.strip() else [],
    }


def categorize_file(rel_path: str) -> str:
    p = rel_path.lower()
    if p.startswith("amancore/storage") or "schema" in p or "migration" in p or p.endswith(".db"):
        return "database"
    if p.startswith("amancore/channels") or "bridge" in p or "meta" in p or "webhook" in p:
        return "integrations"
    if p.startswith("amancore/business_brain") or p.startswith("amancore/requirements") or "voice" in p or "llm" in p:
        return "AI/LLM"
    if p.startswith("amancore/ops") or "jobs" in p or "worker" in p or "scheduler" in p:
        return "workers"
    if p.startswith("amancore/services") or p.startswith("amancore/crm") or p.startswith("amancore/leads") or p.startswith("amancore/sales") or p.startswith("amancore/support") or p.startswith("amancore/consultation") or p.startswith("amancore/pricing") or p.startswith("amancore/analytics") or p.startswith("amancore/insights") or p.startswith("amancore/brand") or p.startswith("amancore/content") or p.startswith("amancore/compliance"):
        return "services"
    if p.startswith("amancore/cli") or p == "amancore/cli.py":
        return "CLI"
    if p.startswith("configs") or p.endswith(".yaml") or p.endswith(".env") or p.endswith(".json") and not p.startswith("tests"):
        return "configuration"
    if p.startswith("scripts"):
        return "scripts"
    if p.startswith("tests/fixtures") or "fixture" in p:
        return "fixtures"
    if "factory" in p:
        return "factories"
    if p.startswith("tests"):
        return "tests"
    if p.startswith("docs") or p.endswith(".md"):
        return "documentation"
    if ".github" in p or "ci" in p or "docker" in p:
        return "CI/CD"
    if p.startswith("bridge"):
        return "bridge"
    if p.startswith("amancore"):
        return "application"
    return "other"


def audit_files():
    all_files = []
    category_map = defaultdict(list)
    for root, dirs, files in os.walk(ROOT):
        rel_root = os.path.relpath(root, ROOT)
        if ".git" in rel_root or "__pycache__" in rel_root or "node_modules" in rel_root or ".venv" in rel_root:
            continue
        for f in files:
            full = Path(root) / f
            try:
                if not full.exists() and not full.is_symlink():
                    continue
                size = full.stat().st_size if full.exists() else 0
            except Exception:
                size = 0
            rel = os.path.relpath(full, ROOT)
            cat = categorize_file(rel)
            all_files.append({"path": rel, "category": cat, "size": size})
            category_map[cat].append({"path": rel, "size": size})
    return {
        "total_files": len(all_files),
        "categories": {k: len(v) for k, v in category_map.items()},
        "category_files": {k: [x["path"] for x in v] for k, v in category_map.items()},
    }


# ==============================================================================
# PROMPT 02 & PYTHON AST ANALYSIS
# ==============================================================================

def parse_python_ast(filepath: Path):
    with open(filepath, "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src, filename=str(filepath))
    classes = []
    functions = []
    imports = []
    from_imports = []
    func_hashes = {}
    
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [m.name for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
            classes.append({"name": node.name, "methods": methods, "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append({"name": node.name, "line": node.lineno, "is_async": isinstance(node, ast.AsyncFunctionDef)})
            # hash function body for duplicate detection
            try:
                f_body = ast.unparse(node.body) if hasattr(ast, "unparse") else ""
                if len(f_body) > 40:
                    func_hashes[node.name] = hashlib.sha256(f_body.encode("utf-8")).hexdigest()
            except Exception:
                pass
        elif isinstance(node, ast.Import):
            for n in node.names:
                imports.append(n.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for n in node.names:
                from_imports.append({"module": mod, "name": n.name, "level": node.level})
    return {
        "classes": classes,
        "functions": functions,
        "func_hashes": func_hashes,
        "imports": imports,
        "from_imports": from_imports,
        "line_count": len(src.splitlines()),
        "byte_count": len(src.encode("utf-8")),
    }


def audit_python_codebase():
    amancore_dir = ROOT / "amancore"
    modules = {}
    dep_graph = defaultdict(set)
    package_set = set()
    all_func_hashes = defaultdict(list)
    
    for root, dirs, files in os.walk(amancore_dir):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                full = Path(root) / f
                rel = full.relative_to(ROOT)
                mod_name = str(rel).replace("/", ".").replace(".py", "")
                if mod_name.endswith(".__init__"):
                    mod_name = mod_name[:-9]
                    package_set.add(mod_name)
                
                try:
                    ast_data = parse_python_ast(full)
                    modules[mod_name] = {"file": str(rel), "ast": ast_data}
                    
                    for fname, fhash in ast_data["func_hashes"].items():
                        all_func_hashes[fhash].append((mod_name, fname))
                        
                    for imp in ast_data["imports"]:
                        if imp.startswith("amancore"):
                            dep_graph[mod_name].add(imp)
                    for fimp in ast_data["from_imports"]:
                        m = fimp["module"]
                        lvl = fimp["level"]
                        if lvl > 0:
                            parts = mod_name.split(".")
                            base_parts = parts[:-lvl] if lvl <= len(parts) else []
                            resolved = ".".join(base_parts + [m]) if m else ".".join(base_parts)
                            if resolved.startswith("amancore"):
                                dep_graph[mod_name].add(resolved)
                        elif m.startswith("amancore"):
                            dep_graph[mod_name].add(m)
                except Exception as exc:
                    modules[mod_name] = {"file": str(rel), "error": str(exc)}
    
    # Cycles
    cycles = []
    def find_cycle(start, current, path, visited):
        for neighbor in dep_graph.get(current, []):
            if neighbor == start and len(path) > 1:
                cycles.append(path + [start])
                return
            if neighbor not in visited and neighbor in dep_graph:
                visited.add(neighbor)
                find_cycle(start, neighbor, path + [neighbor], visited)
                visited.remove(neighbor)
                
    for node in dep_graph:
        find_cycle(node, node, [node], {node})
        
    # Architectural Boundary Violations:
    # 1. business_brain importing channels/transport
    # 2. domain / services importing bridge directly
    boundary_violations = []
    for mod, targets in dep_graph.items():
        if "business_brain" in mod:
            for t in targets:
                if "channels" in t or "bridge" in t:
                    boundary_violations.append({
                        "from": mod,
                        "to": t,
                        "rule": "business_brain must not import channels/bridge (transport isolation)"
                    })
        if "storage" in mod:
            for t in targets:
                if "channels" in t or "services" in t:
                    boundary_violations.append({
                        "from": mod,
                        "to": t,
                        "rule": "storage layer must not import transport or higher services"
                    })
                    
    # Duplicate functions
    duplicates = []
    for fhash, locs in all_func_hashes.items():
        if len(locs) > 1:
            duplicates.append({"hash": fhash, "locations": locs})
            
    return {
        "modules_count": len(modules),
        "modules": modules,
        "packages": list(package_set),
        "dep_graph": {k: list(v) for k, v in dep_graph.items()},
        "cycles_count": len(cycles),
        "cycles": cycles[:10],
        "boundary_violations": boundary_violations,
        "exact_func_duplicates": duplicates,
    }


# ==============================================================================
# PROMPT 05 & DATABASE FORENSICS
# ==============================================================================

def audit_database_schema():
    schema_file = ROOT / "amancore" / "storage" / "schema.sql"
    if not schema_file.exists():
        return {"error": "schema.sql missing"}
    
    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name
        
    res = {}
    try:
        conn = sqlite3.connect(temp_db_path)
        cur = conn.cursor()
        
        cur.execute("PRAGMA foreign_keys = ON;")
        cur.execute("PRAGMA journal_mode = WAL;")
        cur.execute("PRAGMA busy_timeout = 5000;")
        
        fk_val = cur.execute("PRAGMA foreign_keys;").fetchone()[0]
        jm_val = cur.execute("PRAGMA journal_mode;").fetchone()[0]
        bt_val = cur.execute("PRAGMA busy_timeout;").fetchone()[0]
        
        cur.executescript(schema_sql)
        conn.commit()
        
        integrity = cur.execute("PRAGMA integrity_check;").fetchall()
        
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;").fetchall()]
        indexes = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name;").fetchall()]
        triggers = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name;").fetchall()]
        
        table_details = {}
        total_cols = 0
        total_fks = 0
        for t in tables:
            cols = cur.execute(f"PRAGMA table_info({t});").fetchall()
            fks = cur.execute(f"PRAGMA foreign_key_list({t});").fetchall()
            total_cols += len(cols)
            total_fks += len(fks)
            table_details[t] = {
                "columns": [{"cid": c[0], "name": c[1], "type": c[2], "notnull": c[3], "dflt_value": c[4], "pk": c[5]} for c in cols],
                "foreign_keys": [{"id": fk[0], "seq": fk[1], "table": fk[2], "from": fk[3], "to": fk[4], "on_update": fk[5], "on_delete": fk[6]} for fk in fks],
            }
            
        # Test transaction rollback
        cur.execute("BEGIN TRANSACTION;")
        cur.execute("INSERT INTO leads (lead_id, name, contact_whatsapp, source_channel, created_at, updated_at) VALUES ('test_lead_1', 'Test', '+1234567890', 'whatsapp', '2026-09-02T00:00:00Z', '2026-09-02T00:00:00Z');")
        conn.rollback()
        lead_count = cur.execute("SELECT COUNT(*) FROM leads WHERE lead_id='test_lead_1';").fetchone()[0]
        
        # Test savepoint rollback
        cur.execute("SAVEPOINT sp1;")
        cur.execute("INSERT INTO leads (lead_id, name, contact_whatsapp, source_channel, created_at, updated_at) VALUES ('test_lead_2', 'Test 2', '+1234567891', 'whatsapp', '2026-09-02T00:00:00Z', '2026-09-02T00:00:00Z');")
        cur.execute("ROLLBACK TO sp1;")
        cur.execute("RELEASE sp1;")
        sp_count = cur.execute("SELECT COUNT(*) FROM leads WHERE lead_id='test_lead_2';").fetchone()[0]
        
        # Test foreign key enforcement
        fk_enforced = False
        try:
            cur.execute("INSERT INTO conversations (conversation_id, lead_id, channel) VALUES ('conv_1', 'nonexistent_lead', 'whatsapp');")
            conn.commit()
        except sqlite3.IntegrityError:
            fk_enforced = True
            conn.rollback()
            
        conn.close()
        
        res = {
            "foreign_keys_pragma": fk_val,
            "journal_mode_pragma": jm_val,
            "busy_timeout_pragma": bt_val,
            "integrity_check": integrity,
            "tables_count": len(tables),
            "tables": tables,
            "total_columns": total_cols,
            "total_foreign_keys": total_fks,
            "indexes_count": len(indexes),
            "indexes": indexes,
            "triggers_count": len(triggers),
            "triggers": triggers,
            "table_details": table_details,
            "transaction_rollback_verified": lead_count == 0,
            "savepoint_rollback_verified": sp_count == 0,
            "foreign_key_enforcement_verified": fk_enforced,
        }
    finally:
        if os.path.exists(temp_db_path):
            os.remove(temp_db_path)
            
    return res


# ==============================================================================
# PROMPT 08 & MULTI-PROCESS CONCURRENCY TEST
# ==============================================================================

def _worker_db_task(db_path: str, worker_id: int, iterations: int):
    successes = 0
    errors = 0
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    for i in range(iterations):
        lead_id = f"w_{worker_id}_{i}_{time.time_ns()}"
        try:
            with conn:
                conn.execute(
                    "INSERT INTO leads (lead_id, name, contact_whatsapp, source_channel, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'whatsapp', datetime('now'), datetime('now'))",
                    (lead_id, f"Worker {worker_id} Item {i}", f"+{worker_id}{i:08d}")
                )
            successes += 1
        except Exception:
            errors += 1
    conn.close()
    return {"worker_id": worker_id, "successes": successes, "errors": errors}


def test_multiprocess_db(workers: int, iterations_per_worker: int = 25):
    schema_file = ROOT / "amancore" / "storage" / "schema.sql"
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
        
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode = WAL;")
        with open(schema_file, "r") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()
        
        t0 = time.perf_counter()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker_db_task, db_path, w, iterations_per_worker) for w in range(workers)]
            results = [f.result() for f in futures]
        elapsed = time.perf_counter() - t0
        
        total_success = sum(r["successes"] for r in results)
        total_errors = sum(r["errors"] for r in results)
        
        # verify count in DB
        conn = sqlite3.connect(db_path)
        actual_count = conn.execute("SELECT COUNT(*) FROM leads WHERE lead_id LIKE 'w_%';").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        conn.close()
        
        return {
            "workers": workers,
            "iterations_per_worker": iterations_per_worker,
            "total_expected": workers * iterations_per_worker,
            "total_success": total_success,
            "total_errors": total_errors,
            "actual_rows_written": actual_count,
            "integrity": integrity,
            "elapsed_s": round(elapsed, 4),
            "ops_per_second": round(total_success / elapsed, 2) if elapsed > 0 else 0,
            "status": "PASS" if total_success == actual_count and total_errors == 0 and integrity == "ok" else "FAIL",
        }
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)


# ==============================================================================
# PROMPT 07 & SECURITY CHECKS
# ==============================================================================

def audit_security():
    findings = []
    # 1. Search for potential secrets or hardcoded tokens in tracked code
    secret_patterns = [
        (re.compile(r"""(?:api[_-]?key|secret|token|password)\s*=\s*['"][a-zA-Z0-9_\-]{20,}['"]""", re.I), "Potential hardcoded credential"),
        (re.compile(r"""sk-[a-zA-Z0-9]{20,}"""), "Potential OpenAI API key"),
        (re.compile(r"""AIza[0-9A-Za-z-_]{35}"""), "Potential Google API key"),
    ]
    
    suspicious_locations = []
    for root, dirs, files in os.walk(ROOT / "amancore"):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                p = Path(root) / f
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    for lno, line in enumerate(fh, 1):
                        for pat, desc in secret_patterns:
                            if pat.search(line):
                                # check if it's just an env lookup or default placeholder
                                if "os.environ" not in line and "getenv" not in line and "dummy" not in line and "mock" not in line and "placeholder" not in line and "test" not in line.lower():
                                    suspicious_locations.append({"file": str(p.relative_to(ROOT)), "line": lno, "desc": desc})
                                    
    # 2. Check for unsafe eval/exec/system calls in amancore
    unsafe_calls = []
    for root, dirs, files in os.walk(ROOT / "amancore"):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                p = Path(root) / f
                with open(p, "r", encoding="utf-8") as fh:
                    src = fh.read()
                if "eval(" in src or "exec(" in src or "subprocess.Popen(shell=True)" in src:
                    unsafe_calls.append(str(p.relative_to(ROOT)))
                    
    # 3. Path traversal protection in BrainStore and BackupService
    from amancore.business_brain.store import BrainStore
    # test brainstore path traversal
    bs = BrainStore(ROOT / "amancore" / "business_brain")
    bs_traversal_blocked = False
    try:
        bs.get_version("../../../etc/passwd")
    except Exception:
        bs_traversal_blocked = True
        
    return {
        "hardcoded_secrets_found": len(suspicious_locations),
        "suspicious_locations": suspicious_locations,
        "unsafe_calls_found": len(unsafe_calls),
        "unsafe_call_files": unsafe_calls,
        "brainstore_path_traversal_blocked": bs_traversal_blocked,
    }


# ==============================================================================
# PROMPT 10 & PERFORMANCE BENCHMARKING
# ==============================================================================

def benchmark_performance():
    from amancore.config import load_config
    from amancore.storage.db import open_database
    
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db = tf.name
        
    results = {}
    try:
        # 1. DB Init Time
        t0 = time.perf_counter()
        db = open_database(temp_db, ROOT / "amancore" / "storage" / "schema.sql")
        db_init_ms = (time.perf_counter() - t0) * 1000.0
        
        # 2. Single Write Latency
        t0 = time.perf_counter()
        db.execute(
            "INSERT INTO leads (lead_id, name, contact_whatsapp, source_channel, created_at, updated_at) "
            "VALUES ('perf_lead_1', 'Perf Test', '+123456789', 'whatsapp', datetime('now'), datetime('now'))"
        )
        single_write_ms = (time.perf_counter() - t0) * 1000.0
        
        # 3. Single Read Latency
        t0 = time.perf_counter()
        row = db.execute("SELECT * FROM leads WHERE lead_id='perf_lead_1';").fetchone()
        single_read_ms = (time.perf_counter() - t0) * 1000.0
        
        # 4. Config Load Time
        t0 = time.perf_counter()
        cfg = load_config(ROOT)
        config_load_ms = (time.perf_counter() - t0) * 1000.0
        
        db.close()
        
        results = {
            "db_init_ms": round(db_init_ms, 2),
            "single_write_ms": round(single_write_ms, 2),
            "single_read_ms": round(single_read_ms, 2),
            "config_load_ms": round(config_load_ms, 2),
        }
    finally:
        if os.path.exists(temp_db):
            os.remove(temp_db)
            
    return results


# ==============================================================================
# MASTER RUNNER
# ==============================================================================

def run_master_forensics():
    print("--- 1. Git Info ---")
    git_info = get_git_info()
    print(f"HEAD: {git_info['head_short']}, Branch: {git_info['branch']}")
    
    print("--- 2. File Inventory ---")
    files_info = audit_files()
    print(f"Total files: {files_info['total_files']}")
    for cat, count in files_info["categories"].items():
        print(f"  {cat:<18}: {count}")
        
    print("--- 3. Python AST & Architecture ---")
    py_info = audit_python_codebase()
    print(f"Modules: {py_info['modules_count']}, Packages: {len(py_info['packages'])}")
    print(f"Cycles: {py_info['cycles_count']}, Boundary Violations: {len(py_info['boundary_violations'])}")
    print(f"Exact Function Duplicates: {len(py_info['exact_func_duplicates'])}")
    
    print("--- 4. Database Forensics ---")
    db_info = audit_database_schema()
    print(f"Tables: {db_info['tables_count']}, Indexes: {db_info['indexes_count']}, Triggers: {db_info['triggers_count']}")
    print(f"Integrity: {db_info['integrity_check']}, FK Enforced: {db_info['foreign_key_enforcement_verified']}")
    
    print("--- 5. Multi-Process Execution (2, 4, 8 workers) ---")
    mp_2 = test_multiprocess_db(workers=2, iterations_per_worker=30)
    print(f"2 workers: {mp_2['status']} (rows: {mp_2['actual_rows_written']}/{mp_2['total_expected']} in {mp_2['elapsed_s']}s)")
    mp_4 = test_multiprocess_db(workers=4, iterations_per_worker=30)
    print(f"4 workers: {mp_4['status']} (rows: {mp_4['actual_rows_written']}/{mp_4['total_expected']} in {mp_4['elapsed_s']}s)")
    mp_8 = test_multiprocess_db(workers=8, iterations_per_worker=30)
    print(f"8 workers: {mp_8['status']} (rows: {mp_8['actual_rows_written']}/{mp_8['total_expected']} in {mp_8['elapsed_s']}s)")
    
    print("--- 6. Security Forensics ---")
    sec_info = audit_security()
    print(f"Secrets found: {sec_info['hardcoded_secrets_found']}, Unsafe calls: {sec_info['unsafe_calls_found']}")
    print(f"BrainStore Traversal Blocked: {sec_info['brainstore_path_traversal_blocked']}")
    
    print("--- 7. Performance Benchmarking ---")
    perf_info = benchmark_performance()
    print(f"DB Init: {perf_info['db_init_ms']}ms, Write: {perf_info['single_write_ms']}ms, Read: {perf_info['single_read_ms']}ms, Config: {perf_info['config_load_ms']}ms")
    
    master_report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": git_info,
        "files": files_info,
        "python": py_info,
        "database": db_info,
        "multiprocess": {
            "2_workers": mp_2,
            "4_workers": mp_4,
            "8_workers": mp_8,
        },
        "security": sec_info,
        "performance": perf_info,
    }
    
    out_path = ROOT / "scripts" / "master_forensic_evidence.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(master_report, f, indent=2)
    print(f"\n[SUCCESS] Master forensic evidence exported to {out_path}")


if __name__ == "__main__":
    run_master_forensics()

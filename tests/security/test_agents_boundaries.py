import unittest

from amancore.agents.content import ContentAgent
from amancore.agents.research import ResearchAgent


class AgentBoundaryTest(unittest.TestCase):
    def test_research_agent_cannot_send_publish_or_write_brain(self):
        self.assertFalse(hasattr(ResearchAgent, "send_message"))
        self.assertFalse(hasattr(ResearchAgent, "publish"))
        self.assertFalse(hasattr(ResearchAgent, "write_business_brain"))
        self.assertFalse(hasattr(ResearchAgent, "negotiate"))

    def test_content_agent_cannot_send_publish_or_write_brain(self):
        self.assertFalse(hasattr(ContentAgent, "send_message"))
        self.assertFalse(hasattr(ContentAgent, "publish"))
        self.assertFalse(hasattr(ContentAgent, "write_business_brain"))


if __name__ == "__main__":
    unittest.main()

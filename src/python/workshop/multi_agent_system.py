import asyncio
import logging
import os
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from azure.ai.agents.aio import AgentsClient
from azure.ai.agents.models import (
    Agent,
    AgentThread,
    AsyncFunctionTool,
    AsyncToolSet,
    BingGroundingTool,
    CodeInterpreterTool,
    ConnectedAgentTool,
    FileSearchTool,
    MessageRole,
)
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from sales_data import SalesData
from utilities import Utilities
from terminal_colors import TerminalColors as tc

load_dotenv()

class AgentRole(Enum):
    SALES_ANALYST = "sales_analyst"
    MARKET_RESEARCHER = "market_researcher"
    REPORT_GENERATOR = "report_generator"
    COORDINATOR = "coordinator"

@dataclass
class AgentConfig:
    name: str
    role: AgentRole
    instructions_file: str
    tools: List[str]
    description: str

@dataclass
class TaskResult:
    agent_role: AgentRole
    success: bool
    content: str
    artifacts: List[str] = None
    error: Optional[str] = None

class MultiAgentOrchestrator:
    def __init__(self, agents_client: AgentsClient, model_name: str):
        self.agents_client = agents_client
        self.model_name = model_name
        self.utilities = Utilities()
        self.sales_data = SalesData(self.utilities)
        self.specialist_agents: Dict[AgentRole, Agent] = {}
        self.coordinator_agent: Agent = None
        self.thread: AgentThread = None
        
    async def initialize_agents(self):
        """Initialize specialized agents and a coordinator that can call them."""
        print("🔧 Creating specialized agents...")
        
        # Create individual specialist agents first
        await self._create_specialist_agents()
        
        # Create coordinator agent with connected agent tools
        await self._create_coordinator_agent()
        
        # Create a single thread for the coordinator
        self.thread = await self.agents_client.threads.create()
        
    async def _create_specialist_agents(self):
        """Create specialized agents that work as tools for the coordinator."""
        
        # Sales Analyst Agent
        await self.sales_data.connect()
        sales_toolset = AsyncToolSet()
        sales_functions = AsyncFunctionTool({
            self.sales_data.async_fetch_sales_data_using_sqlite_query,
        })
        sales_toolset.add(sales_functions)
        sales_toolset.add(CodeInterpreterTool())
        
        sales_instructions = self.utilities.load_instructions("instructions/multi_agent_sales_analyst.txt")
        
        self.specialist_agents[AgentRole.SALES_ANALYST] = await self.agents_client.create_agent(
            model=self.model_name,
            name="Contoso Sales Analyst",
            instructions=sales_instructions,
            toolset=sales_toolset
        )
        print("✅ Created Sales Analyst agent")
        
        # Market Research Agent
        market_toolset = AsyncToolSet()
        if os.environ.get("AZURE_BING_CONNECTION_ID"):
            bing_grounding = BingGroundingTool(connection_id=os.environ.get("AZURE_BING_CONNECTION_ID"))
            market_toolset.add(bing_grounding)
        
        # Add file search for product documentation
        vector_store = await self.utilities.create_vector_store(
            self.agents_client,
            files=["datasheet/contoso-tents-datasheet.pdf"],
            vector_store_name="Product Documentation",
        )
        file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])
        market_toolset.add(file_search_tool)
        
        market_instructions = self.utilities.load_instructions("instructions/multi_agent_market_researcher.txt")
        
        self.specialist_agents[AgentRole.MARKET_RESEARCHER] = await self.agents_client.create_agent(
            model=self.model_name,
            name="Contoso Market Researcher",
            instructions=market_instructions,
            toolset=market_toolset
        )
        print("✅ Created Market Research agent")
        
        # Report Generator Agent
        report_toolset = AsyncToolSet()
        report_toolset.add(CodeInterpreterTool())
        report_toolset.add(file_search_tool)  # Reuse the same vector store
        
        report_instructions = self.utilities.load_instructions("instructions/multi_agent_report_generator.txt")
        
        self.specialist_agents[AgentRole.REPORT_GENERATOR] = await self.agents_client.create_agent(
            model=self.model_name,
            name="Contoso Report Generator",
            instructions=report_instructions,
            toolset=report_toolset
        )
        print("✅ Created Report Generator agent")
        
    async def _create_coordinator_agent(self):
        """Create coordinator agent with connected agent tools."""
        print("🎯 Creating coordinator agent with connected tools...")

        # Validate that all specialist agents exist
        required_roles = [AgentRole.SALES_ANALYST, AgentRole.MARKET_RESEARCHER, AgentRole.REPORT_GENERATOR]
        for role in required_roles:
            if role not in self.specialist_agents:
                raise ValueError(f"Missing specialist agent: {role}")
            print(f"✓ Verified {role.value} agent: {self.specialist_agents[role].id}")
        
        # Create connected agent tools for each specialist
        connected_tools = []
        
        sales_agent_tool = ConnectedAgentTool(
            id=self.specialist_agents[AgentRole.SALES_ANALYST].id,
            name="sales_analyst",
            description="Analyzes sales data, creates visualizations, calculates metrics, and identifies trends. Can query the Contoso sales database and create charts."
        )
        connected_tools.extend(sales_agent_tool.definitions)
        
        market_agent_tool = ConnectedAgentTool(
            id=self.specialist_agents[AgentRole.MARKET_RESEARCHER].id,
            name="market_researcher", 
            description="Researches competitors, market trends, and external data using Bing search and product documentation analysis."
        )
        connected_tools.extend(market_agent_tool.definitions)
        
        report_agent_tool = ConnectedAgentTool(
            id=self.specialist_agents[AgentRole.REPORT_GENERATOR].id,
            name="report_generator",
            description="Creates comprehensive reports by synthesizing information from multiple sources. Can format professional reports and create summaries."
        )
        connected_tools.extend(report_agent_tool.definitions)
        
        # Load coordinator instructions
        coordinator_instructions = self.utilities.load_instructions("instructions/multi_agent_coordinator.txt")
        
        # Create coordinator agent with all connected agent tools
        self.coordinator_agent = await self.agents_client.create_agent(
            model=self.model_name,
            name="Contoso Multi-Agent Coordinator",
            instructions=coordinator_instructions,
            tools=connected_tools
        )
        print("✅ Created Coordinator agent with connected tools")

    async def execute_complex_task(self, user_request: str) -> str:
        """Execute a complex task using the coordinator agent with connected tools."""
        print(f"🎯 Processing complex task: {user_request}")
        
        # Send the user request directly to the coordinator
        # The coordinator will automatically decide which specialist agents to call
        await self.agents_client.messages.create(
            thread_id=self.thread.id,
            role=MessageRole.USER,
            content=user_request,
        )
        
        print("🤝 Coordinator is orchestrating specialist agents...")
        print("⏳ This may take 1-3 minutes as agents collaborate...")
        
        import time
        start_time = time.time()
        
        try:
            # Add timeout to prevent indefinite hanging
            run = await asyncio.wait_for(
                self.agents_client.runs.create_and_process(
                    thread_id=self.thread.id,
                    agent_id=self.coordinator_agent.id,
                    max_completion_tokens=8192,
                    temperature=0.1,
                ),
                timeout=300.0  # 5 minute timeout
            )
            
            elapsed_time = time.time() - start_time
            print(f"⏱️ Processing completed in {elapsed_time:.1f} seconds")
            
        except asyncio.TimeoutError:
            print("❌ Task timed out after 5 minutes")
            return "Task timed out - one of the specialist agents took too long to respond"
        
        except Exception as e:
            print(f"❌ Error during task execution: {e}")
            import traceback
            traceback.print_exc()
            return f"Error during task execution: {str(e)}"
        
        # Check if the run completed successfully
        if run.status == "completed":
            print("✅ Task completed successfully")
            
            # Get the final response from the coordinator
            messages = await self.agents_client.threads.messages.list(
                thread_id=self.thread.id,
                limit=1,
                order="desc"
            )
            
            response_content = ""
            if messages.data:
                latest_message = messages.data[0]
                if latest_message.role == MessageRole.AGENT and latest_message.content:
                    for content in latest_message.content:
                        if hasattr(content, 'text'):
                            response_content += content.text.value
        
        elif run.status == "failed":
            error_msg = getattr(run, 'last_error', 'Unknown error')
            print(f"❌ Task failed: {error_msg}")
            response_content = f"Task failed: {error_msg}"
            
            # Try to get run steps for debugging
            try:
                run_steps = await self.agents_client.runs.steps.list(
                    thread_id=self.thread.id,
                    run_id=run.id
                )
                
                print(f"\n🔍 Debugging failed run steps:")
                for i, step in enumerate(run_steps.data):
                    print(f"  Step {i+1}: {step.type} - Status: {step.status}")
                    if step.status == "failed" and hasattr(step, 'last_error'):
                        print(f"    Error: {step.last_error}")
                        
            except Exception as debug_error:
                print(f"Could not retrieve run steps: {debug_error}")
        
        elif run.status == "requires_action":
            print(f"⚠️ Task requires manual action - this usually means tool calls are stuck or need approval")
            response_content = "Task requires manual action - tool calls may be stuck or need approval"
            
            # Try to get run steps to see what actions are required
            try:
                run_steps = await self.agents_client.runs.steps.list(
                    thread_id=self.thread.id,
                    run_id=run.id
                )
                
                print(f"\n🔍 Required actions debug:")
                for i, step in enumerate(run_steps.data):
                    print(f"  Step {i+1}: {step.type} - Status: {step.status}")
                    if step.type == "tool_calls" and step.status == "in_progress":
                        print(f"    ⚠️ Tool calls are stuck - likely database timeout or connection issue")
                        
            except Exception as debug_error:
                print(f"Could not retrieve run steps: {debug_error}")
        
        elif run.status in ["cancelled", "expired"]:
            print(f"⚠️ Task was {run.status}")
            response_content = f"Task was {run.status}"
        
        else:
            print(f"⚠️ Task ended with status: {run.status}")
            response_content = f"Task ended with status: {run.status}"
        
        return response_content

    async def cleanup(self):
        """Clean up all agents and threads."""
        print("🧹 Cleaning up agents...")
        
        # Delete coordinator agent
        if self.coordinator_agent:
            await self.agents_client.delete_agent(self.coordinator_agent.id)
            print("✅ Coordinator agent deleted")
        
        # Delete specialist agents
        for role, agent in self.specialist_agents.items():
            await self.agents_client.delete_agent(agent.id)
            print(f"✅ {role.value} agent deleted")
        
        # Delete thread
        if self.thread:
            await self.agents_client.threads.delete(self.thread.id)
            print("✅ Thread deleted")
            
        # Close database connection
        await self.sales_data.close()
        print("✅ Database connection closed")


async def main():
    """Multi-Agent System Demo"""
    print(f"{tc.BOLD}{tc.GREEN}🚀 Contoso Multi-Agent System{tc.RESET}")
    print("This system coordinates multiple specialized agents:")
    print("• 📊 Sales Analyst - Data analysis and visualization")
    print("• 🔍 Market Researcher - Competitive intelligence") 
    print("• 📄 Report Generator - Comprehensive reporting")
    print("• 🎯 Coordinator - Task coordination")
    print()

    # Initialize the multi-agent system
    agents_client = AgentsClient(
        credential=DefaultAzureCredential(),
        endpoint=os.environ["PROJECT_ENDPOINT"],
    )

    orchestrator = MultiAgentOrchestrator(
        agents_client=agents_client,
        model_name=os.getenv("MODEL_DEPLOYMENT_NAME")
    )

    try:
        print("Initializing multi-agent system...")
        await orchestrator.initialize_agents()
        print(f"{tc.GREEN}✅ All agents initialized successfully{tc.RESET}")
        print()

        while True:
            print(f"{tc.CYAN}Enter your complex query (or 'exit' to quit):{tc.RESET}")
            user_input = input("> ").strip()

            if user_input.lower() in ['exit', 'quit']:
                break

            if not user_input:
                continue

            print()
            print(f"{tc.YELLOW}🎯 Processing with multi-agent system...{tc.RESET}")
            print()

            # Execute the complex task using the coordinator
            result = await orchestrator.execute_complex_task(user_input)
            
            print()
            print(f"{tc.GREEN}📋 Final Report:{tc.RESET}")
            print("=" * 60)
            print(result)
            print("=" * 60)
            print()

    except Exception as e:
        print(f"{tc.RED}Error: {e}{tc.RESET}")
    finally:
        print("Cleaning up agents...")
        await orchestrator.cleanup()
        print(f"{tc.GREEN}✅ Cleanup completed{tc.RESET}")


if __name__ == "__main__":
    asyncio.run(main())

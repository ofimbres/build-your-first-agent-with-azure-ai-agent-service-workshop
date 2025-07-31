## Introduction

In the previous labs, you built a single agent capable of handling sales data analysis, file search, code interpretation, and Bing search. While powerful, many real-world scenarios benefit from **multi-agent systems** where specialized agents collaborate to solve complex problems.

### What is a Multi-Agent System?

A multi-agent system consists of multiple AI agents, each with specialized roles and capabilities, working together to accomplish tasks that would be difficult or impossible for a single agent to handle efficiently. Each agent can have:

- **Specialized instructions** tailored to specific domains
- **Distinct tool sets** optimized for particular tasks
- **Unique conversation contexts** for maintaining task-specific state
- **Collaborative workflows** for handoffs and information sharing

### Benefits of Multi-Agent Architecture

1. **Specialization**: Each agent can excel in its specific domain
2. **Scalability**: Tasks can be distributed across multiple agents
3. **Maintainability**: Easier to update and debug individual agent capabilities
4. **Resilience**: Failure of one agent doesn't compromise the entire system
5. **Parallel Processing**: Multiple agents can work simultaneously

## Lab Exercise

In this lab, you'll extend the Contoso Sales Agent into a multi-agent system with three specialized agents:

1. **Sales Analyst Agent**: Handles data queries, analysis, and visualization
2. **Market Research Agent**: Performs competitive analysis using Bing search
3. **Report Generator Agent**: Creates comprehensive reports by coordinating with other agents

This demonstrates how to orchestrate multiple agents using the Foundry Agent Service to create a more sophisticated and capable system.

## Create the Multi-Agent Architecture

### Connected Agents Pattern

The modern approach to multi-agent systems uses **Connected Agents**, where specialist agents are exposed as tools to a coordinator agent. This eliminates the need for manual orchestration and allows the AI to intelligently decide when and how to use each specialist.

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Coordinator Agent                        │
│  ┌─────────────────────────────────────────────────────────┤
│  │ • Receives user requests                                │
│  │ • Decides which specialists to call                     │
│  │ • Orchestrates workflow automatically                   │
│  │ • Synthesizes final response                            │
│  └─────────────────────────────────────────────────────────┤
│                                                             │
│  Tools (Connected Agents):                                 │
│  ┌─────────────┬─────────────────┬──────────────────────┐ │
│  │ Sales       │ Market          │ Report               │ │
│  │ Analyst     │ Researcher      │ Generator            │ │
│  │ Tool        │ Tool            │ Tool                 │ │
│  └─────────────┴─────────────────┴──────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Benefits of Connected Agents

1. **Intelligent Orchestration**: The coordinator decides which agents to call based on the request
2. **Dynamic Workflows**: No hard-coded logic - the AI adapts to different scenarios  
3. **Natural Conversation**: Users interact with one agent that coordinates behind the scenes
4. **Simplified Architecture**: Less manual coordination code to maintain
5. **Better Error Handling**: Built-in retry and fallback mechanisms

=== "Python"

    Create a new file called `multi_agent_system.py` in the `src/python/workshop/` directory:

    ```python
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

    from sales_data import SalesData
    from utilities import Utilities

    class AgentRole(Enum):
        SALES_ANALYST = "sales_analyst"
        MARKET_RESEARCHER = "market_researcher"
        REPORT_GENERATOR = "report_generator"
        ORCHESTRATOR = "orchestrator"

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
                toolset=sales_toolset,
                temperature=0.1,
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
                toolset=market_toolset,
                temperature=0.1,
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
                toolset=report_toolset,
                temperature=0.1,
            )
            print("✅ Created Report Generator agent")
            
        async def _create_coordinator_agent(self):
            """Create coordinator agent with connected agent tools."""
            print("🎯 Creating coordinator agent with connected tools...")
            
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
                tools=connected_tools,
                temperature=0.1,
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
            
            # Stream the coordinator's response
            response_content = ""
            print("🤝 Coordinator is orchestrating specialist agents...")
            
            async with await self.agents_client.runs.stream(
                thread_id=self.thread.id,
                agent_id=self.coordinator_agent.id,
                max_completion_tokens=8192,
                temperature=0.1,
            ) as stream:
                async for update in stream:
                    if hasattr(update, 'delta') and hasattr(update.delta, 'content'):
                        if update.delta.content:
                            for content in update.delta.content:
                                if hasattr(content, 'text'):
                                    response_content += content.text.value
                                    # Print streaming response for better UX
                                    print(content.text.value, end='', flush=True)
                    elif hasattr(update, 'status'):
                        if update.status == 'completed':
                            print("\n✅ Task completed successfully")
                        elif update.status == 'failed':
                            print(f"\n❌ Task failed: {getattr(update, 'last_error', 'Unknown error')}")
            
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
    ```

=== "C#"

    Create a new file called `MultiAgentSystem.cs` in the `src/csharp/workshop/AgentWorkshop.Client/` directory:

    ```csharp
    using Azure.AI.Agents.Persistent;
    using System.Text.Json;

    namespace AgentWorkshop.Client;

    public enum AgentRole
    {
        SalesAnalyst,
        MarketResearcher,
        ReportGenerator,
        Coordinator
    }

    public class MultiAgentOrchestrator : IAsyncDisposable
    {
        private readonly PersistentAgentsClient client;
        private readonly string modelName;
        private readonly SalesData salesData;
        private readonly Dictionary<AgentRole, PersistentAgent> specialistAgents = new();
        private PersistentAgent coordinatorAgent;
        private PersistentAgentThread thread;

        public MultiAgentOrchestrator(PersistentAgentsClient client, string modelName)
        {
            this.client = client;
            this.modelName = modelName;
            this.salesData = new SalesData(Path.Combine(Environment.CurrentDirectory, "..", "..", "..", "..", "..", "..", "shared"));
        }

        public async Task InitializeAgentsAsync()
        {
            Console.WriteLine("🔧 Creating specialized agents...");
            
            // Create specialist agents first
            await CreateSpecialistAgentsAsync();
            
            // Create coordinator with connected agent tools
            await CreateCoordinatorAgentAsync();
            
            // Create thread for coordinator
            thread = await client.Threads.CreateThreadAsync();
        }

        private async Task CreateSpecialistAgentsAsync()
        {
            // Sales Analyst Agent
            var salesTools = new List<ToolDefinition>
            {
                new FunctionToolDefinition(
                    name: nameof(SalesData.FetchSalesDataAsync),
                    description: "Execute SQLite queries against the sales database",
                    parameters: BinaryData.FromObjectAsJson(new {
                        Type = "object",
                        Properties = new {
                            Query = new {
                                Type = "string",
                                Description = "SQLite query to execute"
                            }
                        },
                        Required = new[] { "query" }
                    })
                ),
                new CodeInterpreterToolDefinition()
            };

            var salesInstructions = await File.ReadAllTextAsync(
                Path.Combine("..", "..", "..", "..", "..", "..", "shared", "instructions", "multi_agent_sales_analyst.txt"));

            specialistAgents[AgentRole.SalesAnalyst] = await client.Administration.CreateAgentAsync(
                model: modelName,
                name: "Contoso Sales Analyst",
                instructions: salesInstructions,
                tools: salesTools,
                temperature: 0.1f
            );
            Console.WriteLine("✅ Created Sales Analyst agent");

            // Market Research Agent
            var marketTools = new List<ToolDefinition>();
            
            // Add Bing grounding if available
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AZURE_BING_CONNECTION_ID")))
            {
                marketTools.Add(new BingGroundingToolDefinition(
                    connectionId: Environment.GetEnvironmentVariable("AZURE_BING_CONNECTION_ID")
                ));
            }

            // Add file search
            var datasheet = Path.Combine("..", "..", "..", "..", "..", "..", "shared", "datasheet", "contoso-tents-datasheet.pdf");
            var file = await client.Files.UploadFileAsync(datasheet, PersistentAgentFilePurpose.Agents);
            var vectorStore = await client.VectorStores.CreateVectorStoreAsync([file.Id], "Product Documentation");
            
            marketTools.Add(new FileSearchToolDefinition());
            var marketToolResources = new ToolResources()
            {
                FileSearch = new FileSearchToolResources()
                {
                    VectorStoreIds = { vectorStore.Id }
                }
            };

            var marketInstructions = await File.ReadAllTextAsync(
                Path.Combine("..", "..", "..", "..", "..", "..", "shared", "instructions", "multi_agent_market_researcher.txt"));

            specialistAgents[AgentRole.MarketResearcher] = await client.Administration.CreateAgentAsync(
                model: modelName,
                name: "Contoso Market Researcher",
                instructions: marketInstructions,
                tools: marketTools,
                toolResources: marketToolResources,
                temperature: 0.1f
            );
            Console.WriteLine("✅ Created Market Research agent");

            // Report Generator Agent
            var reportTools = new List<ToolDefinition>
            {
                new CodeInterpreterToolDefinition(),
                new FileSearchToolDefinition()
            };

            var reportInstructions = await File.ReadAllTextAsync(
                Path.Combine("..", "..", "..", "..", "..", "..", "shared", "instructions", "multi_agent_report_generator.txt"));

            specialistAgents[AgentRole.ReportGenerator] = await client.Administration.CreateAgentAsync(
                model: modelName,
                name: "Contoso Report Generator",
                instructions: reportInstructions,
                tools: reportTools,
                toolResources: marketToolResources, // Reuse same vector store
                temperature: 0.1f
            );
            Console.WriteLine("✅ Created Report Generator agent");
        }

        private async Task CreateCoordinatorAgentAsync()
        {
            Console.WriteLine("🎯 Creating coordinator agent with connected tools...");

            var connectedTools = new List<ToolDefinition>();

            // Create connected agent tools
            connectedTools.Add(new ConnectedAgentToolDefinition(
                agentId: specialistAgents[AgentRole.SalesAnalyst].Id,
                name: "sales_analyst",
                description: "Analyzes sales data, creates visualizations, calculates metrics, and identifies trends. Can query the Contoso sales database and create charts."
            ));

            connectedTools.Add(new ConnectedAgentToolDefinition(
                agentId: specialistAgents[AgentRole.MarketResearcher].Id,
                name: "market_researcher",
                description: "Researches competitors, market trends, and external data using Bing search and product documentation analysis."
            ));

            connectedTools.Add(new ConnectedAgentToolDefinition(
                agentId: specialistAgents[AgentRole.ReportGenerator].Id,
                name: "report_generator",
                description: "Creates comprehensive reports by synthesizing information from multiple sources. Can format professional reports and create summaries."
            ));

            var coordinatorInstructions = await File.ReadAllTextAsync(
                Path.Combine("..", "..", "..", "..", "..", "..", "shared", "instructions", "multi_agent_coordinator.txt"));

            coordinatorAgent = await client.Administration.CreateAgentAsync(
                model: modelName,
                name: "Contoso Multi-Agent Coordinator",
                instructions: coordinatorInstructions,
                tools: connectedTools,
                temperature: 0.1f
            );
            Console.WriteLine("✅ Created Coordinator agent with connected tools");
        }

        public async Task<string> ExecuteComplexTaskAsync(string userRequest)
        {
            Console.WriteLine($"🎯 Processing complex task: {userRequest}");

            // Send request to coordinator
            await client.Messages.CreateMessageAsync(thread.Id, MessageRole.User, userRequest);

            var response = "";
            Console.WriteLine("🤝 Coordinator is orchestrating specialist agents...");

            await foreach (var update in client.Runs.CreateRunStreamingAsync(thread.Id, coordinatorAgent.Id))
            {
                if (update is MessageContentUpdate contentUpdate)
                {
                    response += contentUpdate.Text;
                    Console.Write(contentUpdate.Text);
                }
                else if (update is RunUpdate runUpdate)
                {
                    if (runUpdate.Status == "completed")
                    {
                        Console.WriteLine("\n✅ Task completed successfully");
                    }
                    else if (runUpdate.Status == "failed")
                    {
                        Console.WriteLine($"\n❌ Task failed: {runUpdate.LastError?.Message ?? "Unknown error"}");
                    }
                }
            }

            return response;
        }

        public async ValueTask DisposeAsync()
        {
            Console.WriteLine("🧹 Cleaning up agents...");

            if (coordinatorAgent != null)
            {
                await client.Administration.DeleteAgentAsync(coordinatorAgent.Id);
                Console.WriteLine("✅ Coordinator agent deleted");
            }

            foreach (var (role, agent) in specialistAgents)
            {
                await client.Administration.DeleteAgentAsync(agent.Id);
                Console.WriteLine($"✅ {role} agent deleted");
            }

            if (thread != null)
            {
                await client.Threads.DeleteThreadAsync(thread.Id);
                Console.WriteLine("✅ Thread deleted");
            }

            salesData.Dispose();
            Console.WriteLine("✅ Database connection closed");
        }
    }
    ```

### Create Specialized Agent Instructions

Now create instruction files for each specialized agent in the `shared/instructions/` directory:

#### Sales Analyst Instructions

Create `multi_agent_sales_analyst.txt`:

```txt
# Sales Analyst Agent

## Role
You are a specialized sales analyst for Contoso. Your expertise is in:
- Analyzing sales data using SQL queries
- Creating data visualizations (charts, graphs, tables)
- Identifying trends and patterns in sales performance
- Calculating key metrics and KPIs

## Capabilities
- Access to the Contoso sales database via function calling
- Code Interpreter for creating visualizations and reports
- Advanced analytical thinking and data interpretation

## Guidelines
- Always validate data before analysis
- Use appropriate chart types for the data being presented
- Provide clear insights and recommendations based on data
- Focus on actionable intelligence
- When working with other agents, clearly state your findings and methodology

## Data Sources
- Contoso Sales Database (SQLite)
- Product categories: Tents, Sleeping Bags, Backpacks, Climbing Gear
- Geographic regions: North America, Europe, Asia, South America
- Time periods: 2021-2024

## Output Format
- Start with executive summary
- Present data clearly with visualizations when appropriate
- Include methodology and assumptions
- End with actionable recommendations
```

#### Market Research Agent Instructions

Create `multi_agent_market_researcher.txt`:

```txt
# Market Research Agent

## Role
You are a specialized market research analyst for Contoso. Your expertise is in:
- Competitive analysis and intelligence gathering
- Market trend identification
- External data research using Bing search
- Industry benchmarking and positioning analysis

## Capabilities
- Bing search for real-time market intelligence
- Access to product documentation and specifications
- Competitive landscape analysis
- Market trend and pricing research

## Guidelines
- Focus on outdoor gear, camping, and sports equipment markets
- Verify information from multiple sources when possible
- Distinguish between verified facts and market speculation
- Provide context for competitive comparisons
- When collaborating with other agents, share sources and methodology

## Research Areas
- Competitor products and pricing
- Market trends and consumer preferences
- Industry news and developments
- Product reviews and customer sentiment
- Distribution and channel strategies

## Output Format
- Start with key findings summary
- Cite sources and provide context
- Include competitive positioning insights
- Highlight opportunities and threats
- Provide strategic recommendations
```

#### Report Generator Instructions

Create `multi_agent_report_generator.txt`:

```txt
# Report Generator Agent

## Role
You are a specialized report writer for Contoso. Your expertise is in:
- Synthesizing information from multiple sources
- Creating comprehensive business reports
- Data storytelling and narrative development
- Executive summary and recommendation creation

## Capabilities
- Code Interpreter for creating polished reports and visualizations
- Access to product documentation
- Synthesis of analysis from other specialized agents
- Professional report formatting and presentation

## Guidelines
- Integrate insights from all contributing agents
- Create coherent narratives from disparate data points
- Focus on business impact and actionable recommendations
- Use professional business writing style
- Ensure reports are executive-ready

## Report Structure
1. Executive Summary
2. Key Findings
3. Analysis Details (from other agents)
4. Market Context (when available)
5. Recommendations
6. Next Steps
7. Appendices (supporting data/charts)

## Output Format
- Professional business report format
- Clear section headers and organization
- Include relevant charts and visualizations
- Provide both summary and detailed views
- End with clear action items
```

#### Coordinator Instructions

Create `multi_agent_coordinator.txt`:

```txt
# Multi-Agent Coordinator

## Role
You are the intelligent coordinator for Contoso's multi-agent system. You have access to three specialist agents as tools and your job is to orchestrate them to handle complex business requests.

## Available Specialist Agents (as tools)
- **sales_analyst**: Analyzes Contoso sales data, creates visualizations, calculates metrics, and identifies trends. Can query the sales database and create charts.
- **market_researcher**: Researches competitors, market trends, and external data using Bing search and analyzes product documentation.
- **report_generator**: Creates comprehensive reports by synthesizing information from multiple sources and formats professional documents.

## Your Responsibilities
1. **Analyze user requests** to understand what information and insights are needed
2. **Decide which specialist agents to call** based on the request requirements
3. **Coordinate multiple agents** when a task requires different types of analysis
4. **Synthesize results** from different agents into coherent responses
5. **Ensure completeness** by calling all necessary agents for comprehensive answers

## Guidelines
- **For sales/data analysis**: Use the sales_analyst tool
- **For competitive/market research**: Use the market_researcher tool  
- **For comprehensive reports**: Use the report_generator tool after gathering data
- **For complex requests**: Call multiple agents in logical order
- **Always prioritize**: Internal data first, then external research, then synthesis

## Example Workflows

**Sales Performance Query**: 
→ Call sales_analyst for data analysis

**Competitive Analysis**: 
→ Call sales_analyst for internal performance 
→ Call market_researcher for competitor data
→ Call report_generator to synthesize findings

**Strategic Report**: 
→ Call sales_analyst for current performance
→ Call market_researcher for market context  
→ Call report_generator for executive summary

## Response Style
- Be conversational and helpful
- Explain what you're doing ("Let me analyze our sales data first...")
- Present information clearly with proper formatting
- Include insights and recommendations based on the combined analysis
- Always cite which agents provided which information

## Important Notes
- You have direct access to specialist agents through tools - use them actively
- Don't try to answer business questions without consulting the appropriate specialists
- When multiple agents are involved, present a unified, coherent response
- Focus on actionable business insights and recommendations
```

### Create the Main Multi-Agent Interface

=== "Python"

    Create `lab6.py` in the `src/python/workshop/` directory:

    ```python
    import asyncio
    import os
    from azure.ai.agents.aio import AgentsClient
    from azure.identity.aio import DefaultAzureCredential
    from dotenv import load_dotenv
    from multi_agent_system import MultiAgentOrchestrator
    from terminal_colors import TerminalColors as tc

    load_dotenv()

    async def main():
        """Multi-Agent System Demo"""
        print(f"{tc.BOLD}{tc.GREEN}🚀 Contoso Multi-Agent System{tc.ENDC}")
        print("This system coordinates multiple specialized agents:")
        print("• 📊 Sales Analyst - Data analysis and visualization")
        print("• 🔍 Market Researcher - Competitive intelligence") 
        print("• 📄 Report Generator - Comprehensive reporting")
        print("• 🎯 Orchestrator - Task coordination")
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
    ```

=== "C#"

    Create `Lab6.cs` in the `src/csharp/workshop/AgentWorkshop.Client/` directory:

    ```csharp
    using Azure.AI.Agents.Persistent;

    namespace AgentWorkshop.Client;

    public class Lab6 : IAsyncDisposable
    {
        private readonly PersistentAgentsClient client;
        private readonly string modelName;
        private MultiAgentOrchestrator orchestrator;

        public Lab6(PersistentAgentsClient client, string modelName)
        {
            this.client = client;
            this.modelName = modelName;
            this.orchestrator = new MultiAgentOrchestrator(client, modelName);
        }

        public async Task RunAsync()
        {
            Console.WriteLine("🚀 Contoso Multi-Agent System");
            Console.WriteLine("This system coordinates multiple specialized agents:");
            Console.WriteLine("• 📊 Sales Analyst - Data analysis and visualization");
            Console.WriteLine("• 🔍 Market Researcher - Competitive intelligence");
            Console.WriteLine("• 📄 Report Generator - Comprehensive reporting");
            Console.WriteLine("• 🎯 Orchestrator - Task coordination");
            Console.WriteLine();

            try
            {
                Console.WriteLine("Initializing multi-agent system...");
                await orchestrator.InitializeAgentsAsync();
                Utils.LogGreen("✅ All agents initialized successfully");
                Console.WriteLine();

                while (true)
                {
                    Utils.LogCyan("Enter your complex query (or 'exit' to quit):");
                    var userInput = (await Console.In.ReadLineAsync())?.Trim();

                    if (string.IsNullOrEmpty(userInput) || 
                        userInput.Equals("exit", StringComparison.OrdinalIgnoreCase) ||
                        userInput.Equals("quit", StringComparison.OrdinalIgnoreCase))
                    {
                        break;
                    }

                    Console.WriteLine();
                    Utils.LogYellow("🎯 Processing with multi-agent system...");
                    Console.WriteLine();

                    // Execute the complex task using the coordinator
                    var result = await orchestrator.ExecuteComplexTaskAsync(userInput);

                    Console.WriteLine();
                    Utils.LogGreen("📋 Final Report:");
                    Console.WriteLine(new string('=', 60));
                    Console.WriteLine(result);
                    Console.WriteLine(new string('=', 60));
                    Console.WriteLine();
                }
            }
            catch (Exception ex)
            {
                Utils.LogRed($"Error: {ex.Message}");
            }
        }

        public async ValueTask DisposeAsync()
        {
            if (orchestrator != null)
            {
                Console.WriteLine("Cleaning up agents...");
                await orchestrator.DisposeAsync();
                Utils.LogGreen("✅ Cleanup completed");
            }
        }
    }
    ```

## Run the Multi-Agent System

### Update the Main Application

=== "Python"

    Update your `main.py` to include the multi-agent option:

    ```python
    # At the top of main.py, add:
    from lab6 import main as lab6_main

    # In your main function, add an option to run Lab 6:
    print("Select lab to run:")
    print("6. Multi-Agent System")
    
    choice = input("Enter choice (1-6): ")
    if choice == "6":
        await lab6_main()
    ```

=== "C#"

    Update your `Program.cs` to include Lab 6:

    ```csharp
    // In Program.cs, replace the lab instantiation with:
    await using Lab lab = new Lab6(projectClient, apiDeploymentName);
    await lab.RunAsync();
    ```

### Test Multi-Agent Scenarios

Try these complex queries that benefit from multi-agent collaboration:

1. **Comprehensive Market Analysis**:
   ```
   "Create a comprehensive analysis comparing our tent sales performance with competitor offerings and market trends. Include visualizations and strategic recommendations."
   ```

2. **Regional Expansion Strategy**:
   ```
   "Analyze our sales data to identify the best regions for expansion, research competitor presence in those markets, and create a strategic report with recommendations."
   ```

3. **Product Performance Deep Dive**:
   ```
   "Compare our backpack sales across all regions, research competitor pricing and features, and generate a report on how we can improve our market position."
   ```

4. **Competitive Intelligence Report**:
   ```
   "Analyze our climbing gear sales trends, research what competitors are doing in this space, and create a comprehensive competitive intelligence report."
   ```

## Advanced Multi-Agent Patterns

### Agent Communication Patterns

The multi-agent system demonstrates several key patterns:

1. **Sequential Processing**: Agents work in a planned sequence
2. **Shared Context**: Information flows between agents through shared context
3. **Specialized Roles**: Each agent has distinct capabilities and responsibilities
4. **Orchestrated Coordination**: A central orchestrator manages the workflow

### Scaling Multi-Agent Systems

Consider these approaches for more complex scenarios:

1. **Parallel Execution**: Multiple agents working simultaneously
2. **Dynamic Agent Creation**: Creating specialized agents on-demand
3. **Agent Hierarchies**: Sub-agents for very specialized tasks
4. **External Integration**: Agents that interface with external systems

### Error Handling and Resilience

The system includes:

- **Graceful Failure**: Individual agent failures don't crash the system
- **Task Validation**: Each agent validates its inputs and outputs
- **Context Preservation**: Shared context ensures continuity
- **Cleanup Management**: Proper resource cleanup for all agents

## Summary

In this lab, you learned how to:

✅ **Design multi-agent architectures** with specialized roles and capabilities  
✅ **Orchestrate complex workflows** across multiple AI agents  
✅ **Share context and information** between different agents  
✅ **Create collaborative AI systems** that exceed single-agent capabilities  
✅ **Implement agent coordination patterns** for real-world scenarios  

This multi-agent approach opens up possibilities for building sophisticated AI systems that can handle complex, multi-faceted business problems by leveraging the specialized strengths of different agents working in coordination.

The patterns demonstrated here can be extended to create even more sophisticated multi-agent systems for complex enterprise scenarios, real-time collaboration, and advanced AI orchestration workflows.
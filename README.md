<div align="center">

![MUSE — the AI code agent](muse.png)

**MUSE — where ancient inspiration meets modern craft**

[![Version](https://img.shields.io/pypi/v/code-muse?style=for-the-badge&logo=python&label=Version&color=purple)](https://pypi.org/project/code-muse/)
[![Downloads](https://img.shields.io/badge/Downloads-170k%2B-brightgreen?style=for-the-badge&logo=download)](https://pypi.org/project/code-muse/)
[![Python](https://img.shields.io/badge/Python-3.14%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/asx8678/muse/ci.yml?style=for-the-badge&logo=github&label=CI)](https://github.com/asx8678/muse/actions)
[![Tests](https://img.shields.io/github/actions/workflow/status/asx8678/muse/ci.yml?style=for-the-badge&logo=pytest&label=Tests)](https://github.com/asx8678/muse/actions)

[![100% Open Source](https://img.shields.io/badge/100%25-Open%20Source-blue?style=for-the-badge)](https://github.com/asx8678/muse)
[![Pydantic AI](https://img.shields.io/badge/Pydantic-AI-success?style=for-the-badge)](https://github.com/pydantic/pydantic-ai)

[![100% privacy](https://img.shields.io/badge/FULL-Privacy%20commitment-blue?style=for-the-badge)](https://github.com/asx8678/muse/blob/main/README.md#muse-privacy-commitment)

[![GitHub stars](https://img.shields.io/github/stars/asx8678/muse?style=for-the-badge&logo=github)](https://github.com/asx8678/muse/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/asx8678/muse?style=for-the-badge&logo=github)](https://github.com/asx8678/muse/network)

[![Discord](https://img.shields.io/badge/Discord-Community-purple?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/eAGdE4J7Ca)
[![Docs](https://img.shields.io/badge/Read-The%20Docs-blue?style=for-the-badge&logo=readthedocs)](https://muse.dev)

**[⭐ Star this repo if you seek the muse's favor ⭐](#quick-start)**

*"Nine voices, one purpose: to shape raw thought into crafted form." — After Hesiod*

</div>

---



## Overview

In Greek myth, the nine Muses — **Calliope** of epic poetry, **Clio** of history, **Erato** of love verse, **Euterpe** of music, **Melpomene** of tragedy, **Polyhymnia** of sacred hymn, **Terpsichore** of dance, **Thalia** of comedy, and **Urania** of astronomy — breathed inspiration into mortals, transforming raw ambition into enduring craft.

MUSE carries that lineage forward. Each agent is a modern Muse: a specialist that illuminates its domain with precise, disciplined intelligence. Together, they orchestrate your work not with brute force, but with the clarity that comes from mastering a single art.

Where others would throw compute at complexity, MUSE channels inspiration — the oldest and most powerful force in creation. The path of the inspired craftsperson is always the more rewarding one.

MUSE is an AI-powered code generation agent, designed to understand programming tasks, generate high-quality code, and explain its reasoning — an open-source instrument for those who refuse to choose between velocity and elegance.


## Quick start

```bash
uvx code-muse -i
````

If `uvx` still starts an older cached version after a release, refresh the tool
environment:

```bash
uvx --refresh-package code-muse code-muse -i
```

## 🪙 Token Savings

Muse compresses shell command output the way a sculptor removes excess marble — reducing token usage by **60–90%**.

| Strategy | What it does | Savings |
|----------|--------------|---------|
| Git | Compresses status/log/diff into one-liners | ~85% |
| Test | Shows only failures + summary | ~90% |
| Lint | Groups errors by rule, not by file | ~80% |
| Code | Strips comments, trims boilerplate | ~50% |
| Read | Smart-ranged file reading | ~60% |

**Quick start:** Run `/init` in your project to lay the foundation.

See `FEATURES.md` for detailed examples of each strategy.

## Installation

### UV (Recommended)

#### macOS / Linux

```bash
# Install UV if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

uvx code-muse
```

#### Windows

On Windows, we recommend installing code-muse as a global tool for the best experience with keyboard shortcuts (Ctrl+C/Ctrl+X cancellation):

```powershell
# Install UV if you don't have it (run in PowerShell as Admin)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uvx code-muse
```


## Changelog (By Kittylog!)

[📋 View the full changelog on Kittylog](https://kittylog.app/c/asx8678/muse)

## Usage

### Adding Models from models.dev 🆕

While there are several models configured right out of the box from providers like Synthetic, Cerebras, OpenAI, Google, and Anthropic, Muse integrates with [models.dev](https://models.dev) to let you browse and add models from **65+ providers** with a single command:

```bash
/add_model
```

This opens an interactive TUI where you can:
- **Browse providers** - See all available AI providers (OpenAI, Anthropic, Groq, Mistral, xAI, Cohere, Perplexity, DeepInfra, and many more)
- **Preview model details** - View capabilities, pricing, context length, and features
- **One-click add** - Automatically configures the model with correct endpoints and API keys

#### Live API with Offline Fallback

The `/add_model` command fetches the latest model data from models.dev in real-time. If the API is unavailable, it falls back to a bundled database:

```
📡 Fetched latest models from models.dev     # Live API
📦 Using bundled models database              # Offline fallback
```

#### Supported Providers

Muse integrates with https://models.dev giving you access to 65 providers and >1000 different model offerings.

There are **39+ additional providers** that already have OpenAI-compatible APIs configured in models.dev!

These providers are automatically configured with correct OpenAI-compatible endpoints, but have **not** been tested thoroughly:

| Provider | Endpoint | API Key Env Var |
|----------|----------|----------------|
| **xAI** (Grok) | `https://api.x.ai/v1` | `XAI_API_KEY` |
| **Groq** | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| **Mistral** | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` |
| **Together AI** | `https://api.together.xyz/v1` | `TOGETHER_API_KEY` |
| **Perplexity** | `https://api.perplexity.ai` | `PERPLEXITY_API_KEY` |
| **DeepInfra** | `https://api.deepinfra.com/v1/openai` | `DEEPINFRA_API_KEY` |
| **Cohere** | `https://api.cohere.com/compatibility/v1` | `COHERE_API_KEY` |
| **AIHubMix** | `https://aihubmix.com/v1` | `AIHUBMIX_API_KEY` |

#### Smart Warnings

- **⚠️ Unsupported Providers** - Providers like Amazon Bedrock and Google Vertex that require special authentication are clearly marked
- **⚠️ No Tool Calling** - Models without tool calling support show a big warning since they can't use Muse's file/shell tools

### Custom Commands
Create markdown files in `.claude/commands/`, `.github/prompts/`, or `.agents/commands/` to define custom slash commands. The filename becomes the command name and the content runs as a prompt.

```bash
# Create a custom command
echo "# Code Review

Please review this code for security issues." > .claude/commands/review.md

# Use it in Muse
/review with focus on authentication
```

## Requirements

- Python 3.14+
- OpenAI API key (for GPT models)
- Gemini API key (for Google's Gemini models)
- Cerebras API key (for Cerebras models)
- Anthropic key (for Claude models)
- Ollama endpoint available

## Agent Rules

Muse supports `AGENTS.md` files for defining coding standards, project conventions, and behavioral guidelines — the laws of your workshop. These rules cover formatting, naming conventions, architectural patterns, and project-specific instructions.

For examples and more information about agent rules, visit [https://agent.md](https://agent.md)

### AGENTS.md Search Order

Muse loads rules from multiple locations, combining them in order:

| Priority | Location | Purpose |
|----------|----------|----------|
| 1 | `~/.muse/AGENTS.md` | Global rules (applied to all projects) |
| 2 | `.muse/AGENTS.md` | Project rules (preferred location) |
| 3 | `./AGENTS.md` | Project rules (alternate location) |

**Key behaviors:**
- Global and project rules are **combined** (global first, then project)
- `.muse/` directory takes **precedence** over project root
- All filename variants are supported: `AGENTS.md`, `AGENT.md`, `agents.md`, `agent.md`


## Round Robin Model Distribution

Muse supports **Round Robin model distribution** — cycling through configured models the way the Muses cycled through their domains, each taking its turn. This feature automatically rotates through models with each request, maximizing API usage while staying within rate limits.

### Configuration
Add a round-robin model configuration to your `~/.muse/extra_models.json` file:

```bash
export CEREBRAS_API_KEY1=csk-...
export CEREBRAS_API_KEY2=csk-...
export CEREBRAS_API_KEY3=csk-...

```

```json
{
  "qwen1": {
    "type": "cerebras",
    "name": "qwen-3-coder-480b",
    "custom_endpoint": {
      "url": "https://api.cerebras.ai/v1",
      "api_key": "$CEREBRAS_API_KEY1"
    },
    "context_length": 131072
  },
  "qwen2": {
    "type": "cerebras",
    "name": "qwen-3-coder-480b",
    "custom_endpoint": {
      "url": "https://api.cerebras.ai/v1",
      "api_key": "$CEREBRAS_API_KEY2"
    },
    "context_length": 131072
  },
  "qwen3": {
    "type": "cerebras",
    "name": "qwen-3-coder-480b",
    "custom_endpoint": {
      "url": "https://api.cerebras.ai/v1",
      "api_key": "$CEREBRAS_API_KEY3"
    },
    "context_length": 131072
  },
  "cerebras_round_robin": {
    "type": "round_robin",
    "models": ["qwen1", "qwen2", "qwen3"],
    "rotate_every": 5
  }
}
```

Then just use /model and tab to select your round-robin model!

The `rotate_every` parameter controls how many requests are made to each model before rotating to the next one. In this example, the round-robin model will use each Qwen model for 5 consecutive requests before moving to the next model in the sequence.

## Custom Model Timeouts

For custom model endpoints (`custom_openai`, `custom_anthropic`, `custom_gemini`, `cerebras`), you can configure custom timeout values to handle slow or unreliable endpoints. The default timeout for these custom endpoint models is 180 seconds.

**Note:** Other model types have different default timeouts:
- ChatGPT/Codex models: 300 seconds (5 minutes)
- Regular Anthropic models: 180 seconds
- Gemini models: 180 seconds

### Configuration
Add a `timeout` field to your model configuration in `~/.muse/extra_models.json`:

```json
{
  "slow_model": {
    "type": "custom_openai",
    "name": "gpt-4",
    "custom_endpoint": {
      "url": "https://slow-endpoint.example.com/v1",
      "api_key": "$API_KEY",
      "timeout": 600
    }
  },
  "fast_model": {
    "type": "cerebras", 
    "name": "llama3.1-8b",
    "custom_endpoint": {
      "url": "https://api.cerebras.ai/v1",
      "api_key": "$CEREBRAS_API_KEY"
    },
    "timeout": 300
  }
}
```

The `timeout` value can be specified either:
- Inside the `custom_endpoint` object (recommended for endpoint-specific timeouts)
- At the top level of the model config (affects all custom endpoint types)

Timeout values must be positive numbers (integers or floats) representing seconds. If no timeout is specified, the default 180-second timeout is used for custom endpoint models.

---

## Create Your Own Agent

Muse features a flexible agent system — each agent a specialist Muse in its own right — that allows you to work with tailored AI assistants for different domains of craft. The system supports both built-in Python agents and custom JSON agents that you can forge yourself.

## Quick Start

### Check Current Agent
```bash
/agent
```
Shows current active agent and all available agents

### Switch Agent
```bash
/agent <agent-name>
```
Switches to the specified agent

### Create New Agent
```bash
/agent agent-creator
```
Switches to the Agent Creator for building custom agents

### Truncate Message History
```bash
/truncate <N>
```
Truncates the message history to keep only the N most recent messages while protecting the first (system) message. For example:
```bash
/truncate 20
```
Would keep the system message plus the 19 most recent messages, removing older ones from the history.

This is useful for managing context length when you have a long conversation history but only need the most recent interactions.

## Available Agents

### Muse (Default)
- **Name**: `muse`
- **Specialty**: General-purpose coding assistant — the Calliope of code
- **Personality**: Playful, sharp, pedantic about craftsmanship
- **Tools**: Full access to all tools
- **Best for**: All coding tasks, file management, execution
- **Principles**: Clean, concise code following YAGNI, SRP, DRY principles
- **File limit**: Max 600 lines per file (enforced!)

### Agent Creator 🏛️
- **Name**: `agent-creator`
- **Specialty**: Forging custom JSON agent configurations — the Hephaestus of agents
- **Tools**: File operations, reasoning
- **Best for**: Building new specialized agents
- **Features**: Schema validation, guided creation process

## Agent Types

### Python Agents
Built-in agents forged in Python with full system integration:
- Discovered automatically from `code_muse/agents/` directory
- Inherit from `BaseAgent` class
- Full access to system internals
- Examples: `muse`, `agent-creator`

### JSON Agents
Agents you craft yourself, defined in JSON files:
- Stored in user's agents directory
- Easy to create, share, and modify
- Schema-validated configuration
- Custom system prompts and tool access

## Creating Custom JSON Agents

### Using Agent Creator (Recommended)

1. **Switch to Agent Creator**:
   ```bash
   /agent agent-creator
   ```

2. **Request agent creation**:
   ```
   I want to create a Python tutor agent
   ```

3. **Follow guided process** to define:
   - Name and description
   - Available tools
   - System prompt and behavior
   - Custom settings

4. **Test your new agent**:
   ```bash
   /agent your-new-agent-name
   ```

### Manual JSON Creation

Create JSON files in your agents directory following this schema:

```json
{
  "name": "agent-name",              // REQUIRED: Unique identifier (kebab-case)
  "display_name": "Agent Name 🤖",   // OPTIONAL: Pretty name with emoji
  "description": "What this agent does", // REQUIRED: Clear description
  "system_prompt": "Instructions...",    // REQUIRED: Agent instructions
  "tools": ["tool1", "tool2"],        // REQUIRED: Array of tool names
  "user_prompt": "How can I help?",     // OPTIONAL: Custom greeting
  "tools_config": {                    // OPTIONAL: Tool configuration
    "timeout": 60
  }
}
```

#### Required Fields
- **`name`**: Unique identifier (kebab-case, no spaces)
- **`description`**: What the agent does
- **`system_prompt`**: Agent instructions (string or array)
- **`tools`**: Array of available tool names

#### Optional Fields
- **`display_name`**: Pretty display name (defaults to title-cased name + 🤖)
- **`user_prompt`**: Custom user greeting
- **`tools_config`**: Tool configuration object

## Available Tools

Agents can access these tools based on their configuration:

- **`list_files`**: Directory and file listing
- **`read_file`**: File content reading
- **`grep`**: Text search across files
- **`create_file`**: Create new files or overwrite existing ones
- **`replace_in_file`**: Targeted text replacements in existing files
- **`delete_snippet`**: Remove a text snippet from a file
- **`delete_file`**: File deletion
- **`agent_run_shell_command`**: Shell command execution
- **`agent_share_your_reasoning`**: Share reasoning with user

### Tool Access Examples
- **Read-only agent**: `["list_files", "read_file", "grep"]`
- **File editor agent**: `["list_files", "read_file", "create_file", "replace_in_file"]`
- **Full access agent**: All tools (like Muse)

## System Prompt Formats

### String Format
```json
{
  "system_prompt": "You are a helpful coding assistant that specializes in Python development."
}
```

### Array Format (Recommended)
```json
{
  "system_prompt": [
    "You are a helpful coding assistant.",
    "You specialize in Python development.",
    "Always provide clear explanations.",
    "Include practical examples in your responses."
  ]
}
```

## Example JSON Agents

### Python Tutor
```json
{
  "name": "python-tutor",
  "display_name": "Python Tutor 🐍",
  "description": "Teaches Python programming concepts with examples",
  "system_prompt": [
    "You are a patient Python programming tutor.",
    "You explain concepts clearly with practical examples.",
    "You help beginners learn Python step by step.",
    "Always encourage learning and provide constructive feedback."
  ],
  "tools": ["read_file", "create_file", "replace_in_file", "agent_share_your_reasoning"],
  "user_prompt": "What Python concept would you like to learn today?"
}
```

### Code Reviewer
```json
{
  "name": "code-reviewer",
  "display_name": "Code Reviewer 🔍",
  "description": "Reviews code for best practices, bugs, and improvements",
  "system_prompt": [
    "You are a senior software engineer doing code reviews.",
    "You focus on code quality, security, and maintainability.",
    "You provide constructive feedback with specific suggestions.",
    "You follow language-specific best practices and conventions."
  ],
  "tools": ["list_files", "read_file", "grep", "agent_share_your_reasoning"],
  "user_prompt": "Which code would you like me to review?"
}
```

### DevOps Helper
```json
{
  "name": "devops-helper",
  "display_name": "DevOps Helper ⚙️",
  "description": "Helps with Docker, CI/CD, and deployment tasks",
  "system_prompt": [
    "You are a DevOps engineer specialized in containerization and CI/CD.",
    "You help with Docker, Kubernetes, GitHub Actions, and deployment.",
    "You provide practical, production-ready solutions.",
    "You always consider security and best practices."
  ],
  "tools": [
    "list_files",
    "read_file",
    "create_file",
    "replace_in_file",
    "agent_run_shell_command",
    "agent_share_your_reasoning"
  ],
  "user_prompt": "What DevOps task can I help you with today?"
}
```

## File Locations

### JSON Agents Directory
- **All platforms**: `~/.muse/agents/`

### Python Agents Directory
- **Built-in**: `code_muse/agents/` (in package)

## Best Practices

### Naming
- Use kebab-case (hyphens, not spaces)
- Be descriptive: "python-tutor" not "tutor"
- Avoid special characters

### System Prompts
- Be specific about the agent's role
- Include personality traits
- Specify output format preferences
- Use array format for multi-line prompts

### Tool Selection
- Only include tools the agent actually needs
- Most agents need `agent_share_your_reasoning`
- File manipulation agents need `read_file`, `create_file`, `replace_in_file`
- Note: `"edit_file"` still works in tool lists (auto-expands to the three individual tools)
- Research agents need `grep`, `list_files`

### Display Names
- Include relevant emoji for personality
- Make it friendly and recognizable
- Keep it concise

## System Architecture

### Agent Discovery
The system automatically discovers agents by:
1. **Python Agents**: Scanning `code_muse/agents/` for classes inheriting from `BaseAgent`
2. **JSON Agents**: Scanning user's agents directory for `*-agent.json` files
3. Instantiating and registering discovered agents

### JSONAgent Implementation
JSON agents are powered by the `JSONAgent` class (`code_muse/agents/json_agent.py`):
- Inherits from `BaseAgent` for full system integration
- Loads configuration from JSON files with robust validation
- Supports all BaseAgent features (tools, prompts, settings)
- Cross-platform user directory support
- Built-in error handling and schema validation

### BaseAgent Interface
Both Python and JSON agents implement this interface:
- `name`: Unique identifier
- `display_name`: Human-readable name with emoji
- `description`: Brief description of purpose
- `get_system_prompt()`: Returns agent-specific system prompt
- `get_available_tools()`: Returns list of tool names

### Agent Manager Integration
The `agent_manager.py` provides:
- Unified registry for both Python and JSON agents
- Seamless switching between agent types
- Configuration persistence across sessions
- Automatic caching for performance

### System Integration
- **Command Interface**: `/agent` command works with all agent types
- **Tool Filtering**: Dynamic tool access control per agent
- **Main Agent System**: Loads and manages both agent types
- **Cross-Platform**: Consistent behavior across all platforms

## Adding Python Agents

To create a new Python agent:

1. Create file in `code_muse/agents/` (e.g., `my_agent.py`)
2. Implement class inheriting from `BaseAgent`
3. Define required properties and methods
4. Agent will be automatically discovered

Example implementation:

```python
from .base_agent import BaseAgent

class MyCustomAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "my-agent"

    @property
    def display_name(self) -> str:
        return "My Custom Agent ✨"

    @property
    def description(self) -> str:
        return "A custom agent for specialized tasks"

    def get_system_prompt(self) -> str:
        return "Your custom system prompt here..."

    def get_available_tools(self) -> list[str]:
        return [
            "list_files",
            "read_file",
            "grep",
            "create_file",
            "replace_in_file",
            "delete_snippet",
            "delete_file",
            "agent_run_shell_command",
            "agent_share_your_reasoning"
        ]
```

## Troubleshooting

### Agent Not Found
- Ensure JSON file is in correct directory
- Check JSON syntax is valid
- Restart Muse or clear agent cache
- Verify filename ends with `-agent.json`

### Validation Errors
- Use Agent Creator for guided validation
- Check all required fields are present
- Verify tool names are correct
- Ensure name uses kebab-case

### Permission Issues
- Make sure agents directory is writable
- Check file permissions on JSON files
- Verify directory path exists

## Advanced Features

### Tool Configuration
```json
{
  "tools_config": {
    "timeout": 120,
    "max_retries": 3
  }
}
```

### Multi-line System Prompts
```json
{
  "system_prompt": [
    "Line 1 of instructions",
    "Line 2 of instructions",
    "Line 3 of instructions"
  ]
}
```

## Future Extensibility

The agent system is built for expansion — new muses for new domains:

- **Specialized Agents**: Code reviewers, debuggers, architects
- **Domain-Specific Agents**: Web dev, data science, DevOps, mobile
- **Personality Variations**: Different communication styles
- **Context-Aware Agents**: Adapt based on project type
- **Team Agents**: Shared configurations for coding standards
- **Plugin System**: Community-contributed agents

## The Craft of JSON Agents

1. **Easy Customization**: Create agents without Python knowledge
2. **Team Sharing**: JSON agents can be shared across teams
3. **Rapid Prototyping**: Quick agent creation for specific workflows
4. **Version Control**: JSON agents are git-friendly
5. **Built-in Validation**: Schema validation with helpful error messages
6. **Cross-Platform**: Works consistently across all platforms
7. **Backward Compatible**: Doesn't affect existing Python agents

## Implementation Details

### Files in System
- **Core Implementation**: `code_muse/agents/json_agent.py`
- **Agent Discovery**: Integrated in `code_muse/agents/agent_manager.py`
- **Command Interface**: Works through existing `/agent` command
- **Testing**: Comprehensive test suite in `tests/test_json_agents.py`

### JSON Agent Loading Process
1. System scans `~/.muse/agents/` for `*-agent.json` files
2. `JSONAgent` class loads and validates each JSON configuration
3. Agents are registered in unified agent registry
4. Users can switch to JSON agents via `/agent <name>` command
5. Tool access and system prompts work identically to Python agents

### Error Handling
- Invalid JSON syntax: Clear error messages with line numbers
- Missing required fields: Specific field validation errors
- Invalid tool names: Warning with list of available tools
- File permission issues: Helpful troubleshooting guidance

## Future Possibilities

- **Agent Templates**: Pre-built JSON agents for common tasks
- **Visual Editor**: GUI for creating JSON agents
- **Hot Reloading**: Update agents without restart
- **Agent Marketplace**: Share and discover community agents
- **Enhanced Validation**: More sophisticated schema validation
- **Team Agents**: Shared configurations for coding standards

## Contributing

### Releases

Maintainer release steps live in [docs/RELEASING.md](docs/RELEASING.md).

### Sharing JSON Agents
1. Create and test your agent thoroughly
2. Ensure it follows best practices
3. Submit a pull request with agent JSON
4. Include documentation and examples
5. Test across different platforms

### Python Agent Contributions
1. Follow existing code style
2. Include comprehensive tests
3. Document the agent's purpose and usage
4. Submit pull request for review
5. Ensure backward compatibility

### Agent Templates
Consider contributing agent templates for:
- Code reviewers and auditors
- Language-specific tutors
- DevOps and deployment helpers
- Documentation writers
- Testing specialists

---

## Security & Trust Boundaries

Muse guards your workshop with the vigilance of a temple guardian — multiple safety layers protect your secrets, filesystem, and runtime:

- **Sessions use JSON by default** — legacy pickle sessions are rejected unless explicitly imported with `--import-legacy-pickle-session` (RCE risk warning).
- **Secrets are redacted** — token files are created with `0o600`, logs scrub `Authorization: Bearer ...` and sensitive query params, and token length is never logged.
- **Shell commands require approval by default** — `yolo_mode` is off; background commands require approval before `Popen`.
- **Workspace boundaries** — file tools enforce cwd containment, block sensitive paths (`.env`, `.ssh`, etc.), and cap huge files/diffs before full read.
- **Hook trust** — project hooks from `.claude/settings.json` require explicit trust (keyed by content hash); untrusted hooks are blocked.
- **Universal Constructor safety** — user-generated tools run in a subprocess worker with JSON-only serialization, dangerous patterns (`eval`, `exec`, `subprocess`) are blocked or approval-gated, and timeouts kill the worker process.
- **Grep safety** — search patterns are passed after `--` so they are treated as data, not CLI flags.

Run `/safety` or `/status` inside Muse to inspect the current risk posture — no secrets exposed.

For full details, see [docs/SECURITY.md](docs/SECURITY.md).

---

# Muse Privacy Commitment

**Zero-compromise privacy. Always.**

Unlike other agentic coding tools, this project has no corporate or investor backing — meaning **zero pressure to compromise our principles for profit**. Privacy isn't a feature we bolted on; it is the bedrock on which Muse was built.

### What Muse _absolutely does not_ collect — now and forever:
- ❌ **Zero telemetry** – no usage analytics, crash reports, or behavioral tracking
- ❌ **Zero prompt logging** – your code, conversations, or project details are never stored
- ❌ **Zero behavioral profiling** – we don't track what you build, how you code, or when you use the tool
- ❌ **Zero third-party data sharing** – your information is never sold, traded, or given away

### What data flows where:
- **LLM Provider Communication**: Your prompts are sent directly to whichever LLM provider you've configured (OpenAI, Anthropic, local models, etc.) – this is unavoidable for AI functionality
- **Complete Local Option**: Run your own VLLM/SGLang/Llama.cpp server locally → **zero data leaves your network**. Configure this with `~/.muse/extra_models.json`
- **Direct Developer Contact**: All feature requests, bug reports, and discussions happen directly with me – no middleman analytics platforms or customer data harvesting tools

### The privacy-first architecture:
Muse is designed with privacy-by-design principles. Every feature has been evaluated through a privacy lens, and every integration respects your data sovereignty. When you use Muse, you are the craftsperson — never the product.

**This commitment is structurally impossible to violate.** No external pressures, no investor demands, no quarterly earnings targets. Just principled code that respects your craft and your privacy.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---
name: auto-dev-team
description: Quickly initialize an agile software team (Product Manager, Developer, and Tester agents) in an empty workspace. Use this skill when the user asks to quickly set up the product, developer, and tester workflow in a new folder.
---
# Auto Dev Team Setup

This skill instantly initializes a multi-agent agile team in the current workspace. It sets up three personas:
1. **Product Manager (Main Agent)**: Coordinates the project.
2. **Developer (Sub-Agent)**: Writes and modifies the code.
3. **Tester (Sub-Agent)**: Tests the code and reports bugs.

## Execution

Run the included `setup_team.sh` script to automatically generate the necessary `GEMINI.md` and `.gemini/agents/*.md` files in the user's current working directory.

Execute the following bash command using the `run_shell_command` tool:

```bash
bash "${__dirname}/scripts/setup_team.sh"
```

After the script runs successfully, tell the user that the agile team (PM + Developer + Tester) has been successfully initialized in their current directory.

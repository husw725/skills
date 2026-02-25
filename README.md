# My Gemini CLI Skills

This repository contains my custom skills for the Gemini CLI.

## Included Skills

- **auto-dev-team**: Quickly initialize an agile software team (Product Manager, Developer, and Tester agents) in an empty workspace.
- **comfyui-runner**: Execute a ComfyUI workflow JSON by connecting to a ComfyUI server.

## How to Import and Use These Skills on Another Computer

To use these skills on a different machine, you can clone this repository and link it to your Gemini CLI.

### Step-by-Step Instructions

1. **Clone the Repository**
   Open your terminal on the new computer and clone this repository into a directory (for example, `~/my-gemini-skills`):
   ```bash
   git clone https://github.com/husw725/skills.git ~/my-gemini-skills
   ```

2. **Link the Skills Directory**
   Use the `gemini skills link` command to tell Gemini CLI to use the skills from this cloned repository:
   ```bash
   gemini skills link ~/my-gemini-skills
   ```

3. **Verify Installation**
   Check that the skills are successfully installed by listing them:
   ```bash
   gemini skills list
   ```

*(Alternatively, you can install individual skills directly using `gemini skills install https://github.com/husw725/skills.git/auto-dev-team` if the structure allows, but linking the entire repository is the easiest way to keep everything synced.)*

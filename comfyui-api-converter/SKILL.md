---
name: comfyui-api-converter
description: Converts standard ComfyUI workflow JSONs into system-compatible API workflows with S3 input/output support and [Param] naming conventions.
---

# ComfyUI API Workflow Converter

This skill automates the process of wrapping a regular ComfyUI workflow into an API-ready format.

## Core Conversion Principles

### 1. Input Node Wrapping
Any parameter that needs to be exposed via API must be converted to a `[Param]` node.
- **Node Type**: Use `PrimitiveString`, `PrimitiveInt`, `PrimitiveFloat`, or `easy boolean`.
- **Title**: Prefix the node title with `[Param]` (e.g., `[Param]Prompt`, `[Param]Width`).
- **Visuals**: Use `color: "#322", bgcolor: "#533"` for easy identification.

### 2. S3 Resource Handling
Inputs representing images or files must accept a **relative S3 path** as the parameter.
- **Workflow Pattern**:
  1. `[Param]S3 Image Path` (PrimitiveString)
  2. `DownloadFileS3` (husw725/comfyS3_alta)
  3. `Alta:LoadImageFromPath` (husw725/comfyui_alta_nodes)
- **Local Path Prefix**: Use `input/temp/` as the default local destination.

### 3. Output Configuration
The final result must be saved back to S3.
- **Nodes**:
  1. `[Param]S3 Output Path` (PrimitiveString)
  2. `SaveImageWithBucketPathS3` (husw725/comfyS3_alta)
  3. `easy showAnything` (comfyui-easy-use)
- **Batching**: If `Batch Size > 1`, the system handles sequential naming (e.g., `result_1.png`, `result_2.png`).

### 4. Handling Subgraphs
Core logic is often encapsulated in a Subgraph.
- The `[Param]` nodes must live in the **top-level** workflow.
- Connect these top-level nodes to the subgraph's input slots.
- Ensure subgraph output images flow into `SaveImageWithBucketPathS3`.

### 5. Constraints & Exclusions
- **Model Names**: Avoid exposing `lora_name` or `checkpoint_name` as `[Param]` if they refer to local server resources. These strings can cause errors if passed incorrectly. Fixed internal values are preferred.
- **Batch Results**: For multi-image batches, only use one `SaveImageWithBucketPathS3` node.

## Node Specifications
For details on specific node inputs and outputs, refer to [node_specs.md](references/node_specs.md).

## Workflow Execution
1. Analyze the original workflow to identify key inputs (LoadImage, CLIPTextEncode, etc.).
2. Locate the core processing node or subgraph.
3. Construct a new top-level JSON structure.
4. Add `[Param]` nodes for inputs and the S3 output path.
5. Create the S3-to-Local download chain for image inputs.
6. Connect all inputs to the processing engine.
7. Add the S3 upload chain to the final image output.
8. Verify all links and node IDs.

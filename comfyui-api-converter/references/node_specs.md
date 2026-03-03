# ComfyUI API Nodes Reference

These specific nodes are required for the system's S3-based API workflow.

## Input Nodes (Download from S3)

### DownloadFileS3 (husw725/comfyS3_alta)
Used to fetch files from S3 to local storage.
- **Inputs**:
    - `s3_path` (STRING): The relative path in S3 (e.g., `aigc/uploads/8.jpg`).
    - `local_path` (STRING): The destination local path (e.g., `input/temp/8.jpg`).
- **Outputs**:
    - `local_path` (STRING): The confirmed local file path.

### Alta:LoadImageFromPath (husw725/comfyui_alta_nodes)
Loads an image from a local absolute path.
- **Inputs**:
    - `path` (STRING): The local absolute path.
- **Outputs**:
    - `image` (IMAGE): The loaded image object.

## Output Nodes (Upload to S3)

### SaveImageWithBucketPathS3 (husw725/comfyS3_alta)
Saves generated images back to S3.
- **Inputs**:
    - `images` (IMAGE): The image(s) to upload.
    - `s3_paths` (STRING): The target relative path in S3.
- **Outputs**:
    - `s3_image_paths` (STRING): The final S3 location.

### easy showAnything (comfyui-easy-use)
The final terminal node that the system uses to identify the output.
- **Inputs**:
    - `anything` (*): Usually connected to the `s3_image_paths` output.

import urllib.request
import urllib.error
import urllib.parse
import json
import time
import argparse
import os

def queue_prompt(prompt, server_address="10.0.6.136:8188"):
    p = {"prompt": prompt}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    try:
        response = urllib.request.urlopen(req)
        return json.loads(response.read())
    except urllib.error.URLError as e:
        if hasattr(e, 'read'):
            print(f"Failed to queue prompt: {e} - Response: {e.read().decode('utf-8')}")
        else:
            print(f"Failed to queue prompt: {e}")
        return None

def get_history(prompt_id, server_address="10.0.6.136:8188"):
    req = urllib.request.Request(f"http://{server_address}/history/{prompt_id}")
    try:
        response = urllib.request.urlopen(req)
        return json.loads(response.read())
    except urllib.error.URLError as e:
        print(f"Failed to get history: {e}")
        return None

def get_image(filename, subfolder, folder_type, server_address="10.0.6.136:8188"):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    req = urllib.request.Request(f"http://{server_address}/view?{url_values}")
    try:
        response = urllib.request.urlopen(req)
        return response.read()
    except urllib.error.URLError as e:
        print(f"Failed to download file {filename}: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Run a ComfyUI workflow from a JSON file")
    parser.add_argument("workflow_json", help="Path to the workflow JSON file")
    parser.add_argument("--server", default="10.0.6.136:8188", help="ComfyUI server address (e.g., 10.0.6.136:8188)")
    parser.add_argument("--outdir", default="./output", help="Directory to save output files")
    args = parser.parse_args()

    with open(args.workflow_json, "r") as f:
        workflow = json.load(f)

    print(f"Queueing workflow to {args.server}...")
    prompt_res = queue_prompt(workflow, server_address=args.server)
    if not prompt_res or "prompt_id" not in prompt_res:
        print("Failed to get prompt_id from server.")
        return
        
    prompt_id = prompt_res["prompt_id"]
    print(f"Prompt queued. ID: {prompt_id}")
    print("Waiting for completion...")
    
    while True:
        history = get_history(prompt_id, server_address=args.server)
        if history and prompt_id in history:
            print("Workflow finished executing.")
            history_data = history[prompt_id]
            outputs = history_data.get("outputs", {})
            
            os.makedirs(args.outdir, exist_ok=True)
            saved_files = []
            
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img in node_output["images"]:
                        filename = img.get("filename")
                        subfolder = img.get("subfolder", "")
                        folder_type = img.get("type", "output")
                        
                        img_data = get_image(filename, subfolder, folder_type, server_address=args.server)
                        if img_data:
                            out_path = os.path.join(args.outdir, filename)
                            with open(out_path, "wb") as out_f:
                                out_f.write(img_data)
                            saved_files.append(out_path)
                elif "gifs" in node_output:
                     for gif in node_output["gifs"]:
                        filename = gif.get("filename")
                        subfolder = gif.get("subfolder", "")
                        folder_type = gif.get("type", "output")
                        
                        gif_data = get_image(filename, subfolder, folder_type, server_address=args.server)
                        if gif_data:
                            out_path = os.path.join(args.outdir, filename)
                            with open(out_path, "wb") as out_f:
                                out_f.write(gif_data)
                            saved_files.append(out_path)

            print(f"Saved {len(saved_files)} files:")
            for sf in saved_files:
                print(f"  - {sf}")
            break
        
        # We can also check /queue to see if it's still there
        try:
            req = urllib.request.Request(f"http://{args.server}/queue")
            response = urllib.request.urlopen(req)
            queue_data = json.loads(response.read())
            
            pending = [p[1] for p in queue_data.get("queue_running", []) + queue_data.get("queue_pending", [])]
            if prompt_id not in pending and not history:
                 # It might be in history now, will be caught next loop. Or it failed.
                 pass
        except Exception as e:
            pass

        time.sleep(1)

if __name__ == "__main__":
    main()

import urllib.request
import urllib.error
import urllib.parse
import json
import time
import argparse
import os
import sys

def get_headers(args):
    headers = {}
    if args.cookie:
        headers["Cookie"] = args.cookie
    return headers

def queue_prompt(prompt, server_address="10.0.6.136:8188", headers=None):
    p = {"prompt": prompt}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data, headers=headers or {})
    try:
        response = urllib.request.urlopen(req)
        return json.loads(response.read())
    except urllib.error.URLError as e:
        if hasattr(e, 'read'):
            print(f"Failed to queue prompt: {e} - Response: {e.read().decode('utf-8')}")
        else:
            print(f"Failed to queue prompt: {e}")
        return None

def get_history(prompt_id, server_address="10.0.6.136:8188", headers=None):
    req = urllib.request.Request(f"http://{server_address}/history/{prompt_id}", headers=headers or {})
    try:
        response = urllib.request.urlopen(req)
        return json.loads(response.read())
    except urllib.error.URLError as e:
        print(f"Failed to get history: {e}")
        return None

def get_image(filename, subfolder, folder_type, server_address="10.0.6.136:8188", headers=None):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    req = urllib.request.Request(f"http://{server_address}/view?{url_values}", headers=headers or {})
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
    parser.add_argument("--cookie", help="Optional: Cookie string to pass in request headers (e.g. for authentication)", default=None)
    args = parser.parse_args()

    with open(args.workflow_json, "r") as f:
        try:
            workflow = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON file. {e}")
            sys.exit(1)

    # Detect Web UI format vs API format
    if isinstance(workflow, dict) and "nodes" in workflow and isinstance(workflow["nodes"], list):
        print("---------------------------------------------------------------------------------")
        print("ERROR: It looks like you provided a ComfyUI Web UI format JSON, not an API format JSON.")
        print("The API endpoint only accepts the 'API Format'.")
        print("To get the correct format:")
        print("1. Open ComfyUI settings (gear icon)")
        print("2. Check 'Enable Dev mode Options'")
        print("3. Close settings and click the new 'Save (API Format)' button in the menu.")
        print("---------------------------------------------------------------------------------")
        sys.exit(1)

    headers = get_headers(args)

    print(f"Queueing workflow to {args.server}...")
    prompt_res = queue_prompt(workflow, server_address=args.server, headers=headers)
    if not prompt_res or "prompt_id" not in prompt_res:
        print("Failed to get prompt_id from server.")
        sys.exit(1)
        
    prompt_id = prompt_res["prompt_id"]
    print(f"Prompt queued. ID: {prompt_id}")
    print("Waiting for completion...")
    
    while True:
        history = get_history(prompt_id, server_address=args.server, headers=headers)
        if history and prompt_id in history:
            print("\nWorkflow finished executing.")
            history_data = history[prompt_id]
            
            # Check for errors in history
            status = history_data.get("status", {})
            if status.get("status_str") == "error":
                print("\n=== EXECUTION FAILED ===")
                for msg in status.get("messages", []):
                    if isinstance(msg, list) and len(msg) >= 2 and msg[0] == "execution_error":
                        err_detail = msg[1]
                        print(f"Failed Node ID   : {err_detail.get('node_id')}")
                        print(f"Failed Node Type : {err_detail.get('node_type')}")
                        print(f"Exception Message: {err_detail.get('exception_message')}")
                        
                        tb = err_detail.get('traceback', [])
                        if tb:
                            print("\nTraceback:")
                            for line in tb:
                                print(line, end="")
                print("========================\n")
                sys.exit(1)

            outputs = history_data.get("outputs", {})
            
            os.makedirs(args.outdir, exist_ok=True)
            saved_files = []
            
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img in node_output["images"]:
                        filename = img.get("filename")
                        subfolder = img.get("subfolder", "")
                        folder_type = img.get("type", "output")
                        
                        img_data = get_image(filename, subfolder, folder_type, server_address=args.server, headers=headers)
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
                        
                        gif_data = get_image(filename, subfolder, folder_type, server_address=args.server, headers=headers)
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
            req = urllib.request.Request(f"http://{args.server}/queue", headers=headers)
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
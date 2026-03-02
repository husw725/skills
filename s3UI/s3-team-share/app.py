import streamlit as st
import boto3
import os
import requests
import jwt
import base64
import random
import string
import json
from botocore.exceptions import ClientError
from botocore.config import Config
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5, AES
from Crypto.Util.Padding import pad

# --- Configuration & Security ---
ADMIN_USERS = ["husw", "alta"]

def restore(hex_str):
    """Safely restore sensitive strings from hex encoding."""
    try: return bytes.fromhex(hex_str).decode('utf-8')
    except: return ""

# Obfuscated credentials (Hex encoded)
H_AK = "414b4941323245353642435032424f4e37524144" 
H_SK = "684831433254632b67456d4c763852624f7057434d41784f6144714d6854594f35757038436c492f" 
H_RSA = "4d4677774451594a4b6f5a496876634e41514542425141445377417753414a42414b6f52386d583072474b4c717a63576d4f7a62666a36344b385a49674f64486e7a6b58534f564f5a6246752f544a685a377246414e2b6561476b6c3343346275636351642f456a45736a39697237696a54376839364d434177454141513d3d"

REGION = "us-east-1"
BUCKET = "starlitshorts"
ROOT_PREFIX = "aigc/drama/"

API_TEST = "https://kkshort-adsmanager-dev.mikktv.xyz/adsmanager/auth/login"
API_PROD = "https://mflixapi.starlitshorts.com/adsmanager/auth/login"

# --- Crypto Utils ---
def generate_aes_key():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(32))

def rsa_encrypt_data(text, pub_key_str):
    pem = f"-----BEGIN PUBLIC KEY-----\n{pub_key_str}\n-----END PUBLIC KEY-----"
    key = RSA.import_key(pem)
    cipher = PKCS1_v1_5.new(key)
    return base64.b64encode(cipher.encrypt(text.encode('utf-8'))).decode('utf-8')

def aes_encrypt_data(data_str, aes_key_str):
    cipher = AES.new(aes_key_str.encode('utf-8'), AES.MODE_ECB)
    padded = pad(data_str.encode('utf-8'), AES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode('utf-8')

# --- State Management ---
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'team' not in st.session_state: st.session_state.team = ""
if 'lang' not in st.session_state: st.session_state.lang = "en"
if 'current_path' not in st.session_state: st.session_state.current_path = ""
if 'init_path' not in st.session_state: st.session_state.init_path = ""

# --- S3 Functions ---
def get_s3_client():
    return boto3.client('s3', aws_access_key_id=restore(H_AK), aws_secret_access_key=restore(H_SK), region_name=REGION, config=Config(signature_version='s3v4'))

def list_contents(prefix):
    s3 = get_s3_client()
    try:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, Delimiter='/')
        return [p.get('Prefix') for p in response.get('CommonPrefixes', [])], response.get('Contents', [])
    except Exception as e:
        st.error(f"S3 Error: {e}")
        return [], []

def find_folder_for_dept(root, dept_name):
    s3 = get_s3_client()
    try:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix=root, Delimiter='/')
        prefixes = [p.get('Prefix') for p in response.get('CommonPrefixes', [])]
        for p in prefixes:
            if p.rstrip('/').split('/')[-1] == dept_name: return p
            res = find_folder_for_dept(p, dept_name)
            if res: return res
    except: pass
    return None

def perform_login(username, password, api_url, is_prod=False):
    payload = {"username": username, "password": password, "clientId": "428a8310cd442757ae699df5d894f051", "grantType": "password", "tenantId": "107184"}
    headers = {"Accept": "application/json", "clientid": "428a8310cd442757ae699df5d894f051", "Content-Type": "application/json"}
    if is_prod:
        try:
            aes_key = generate_aes_key()
            aes_b64 = base64.b64encode(aes_key.encode('utf-8')).decode('utf-8')
            headers["encrypt-key"] = rsa_encrypt_data(aes_b64, restore(H_RSA))
            encrypted_body = aes_encrypt_data(json.dumps(payload, separators=(',', ':')), aes_key)
            data = json.dumps(encrypted_body)
        except Exception as e: return False, f"Encryption Error: {e}"
    else: data = json.dumps(payload)
    try:
        resp = requests.post(api_url, data=data, headers=headers, timeout=15)
        res_data = resp.json()
        if res_data.get("code") == 200:
            token = res_data.get("data", {}).get("access_token")
            return True, jwt.decode(token, options={"verify_signature": False})
        return False, res_data.get("msg", "Unknown error")
    except Exception as e: return False, str(e)

# --- UI Layout ---
st.set_page_config(page_title="S3 Team Share", layout="wide")
st.sidebar.title("Settings")
st.session_state.lang = st.sidebar.selectbox("Language / 语言", ["en", "zh"])
t = {
    "en": {"login": "Login", "user": "Username", "pwd": "Password", "env": "Env", "btn": "Sign In", "back": "Parent Dir", "new": "New Folder", "del": "Delete", "upload": "Upload", "start": "Start Upload"},
    "zh": {"login": "登录", "user": "用户名", "pwd": "密码", "env": "环境", "btn": "进入系统", "back": "返回上级", "new": "新建文件夹", "del": "删除", "upload": "上传文件", "start": "开始上传"}
}[st.session_state.lang]

if not st.session_state.logged_in:
    st.title(t["login"])
    # Environment selection hidden for production delivery
    # env_choice = st.radio(t["env"], ["Release", "Test"])
    env_choice = "Release" 
    st.session_state.env = env_choice
    
    with st.form("login"):
        u = st.text_input(t["user"])
        p = st.text_input(t["pwd"], type="password")
        if st.form_submit_button(t["btn"]):
            success, res = perform_login(u, p, API_PROD if env_choice == "Release" else API_TEST, is_prod=(env_choice == "Release"))
            if success:
                st.session_state.logged_in = True
                user_name, dept_name = res.get("userName", u), res.get("deptName", "Unknown")
                env_f = "release" if env_choice == "Release" else "test"
                path = find_folder_for_dept(f"{ROOT_PREFIX}{env_f}/", dept_name)
                if not path: path = f"{ROOT_PREFIX}{env_f}/{dept_name}/"
                st.session_state.user_role, st.session_state.team, st.session_state.current_path = ("admin" if user_name.lower() in [au.lower() for au in ADMIN_USERS] else "user"), dept_name, path
                st.session_state.init_path = path
                st.rerun()
            else: st.error(f"Error: {res}")
else:
    st.title(f"📁 S3 Share")
    st.subheader(f"Welcome, {st.session_state.user_role} ({st.session_state.team})")
    if st.sidebar.button("Logout"): st.session_state.logged_in = False; st.rerun()
    col_nav, col_new = st.columns([3, 1])
    with col_nav:
        # Display simplified path
        if st.session_state.current_path.startswith(st.session_state.init_path):
            dp = "/" + st.session_state.current_path.replace(st.session_state.init_path, "")
        else: dp = "ROOT/" + st.session_state.current_path.replace(ROOT_PREFIX, "")
        st.write(f"**Path:** `{dp}`")

        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            base = ROOT_PREFIX if st.session_state.user_role == "admin" else st.session_state.init_path
            if st.session_state.current_path != base:
                if st.button(t["back"], use_container_width=True):
                    st.session_state.current_path = "/".join(st.session_state.current_path.rstrip('/').split('/')[:-1]) + "/"
                    st.rerun()
        with btn_col2:
            if st.button("🔄 " + ("Refresh" if st.session_state.lang == "en" else "刷新"), use_container_width=True):
                st.rerun()

            fn = st.text_input("Name")
            if st.button("Create"):
                get_s3_client().put_object(Bucket=BUCKET, Key=f"{st.session_state.current_path}{fn}/", Body=""); st.rerun()
    st.divider()
    f_up = st.file_uploader(t["upload"], label_visibility="collapsed")
    if f_up and st.button(t["start"]):
        with st.spinner("Uploading..."):
            get_s3_client().upload_fileobj(f_up, BUCKET, f"{st.session_state.current_path}{f_up.name}"); st.success("Done"); st.rerun()
    st.divider()
    dirs, f_list = list_contents(st.session_state.current_path)
    for d in dirs:
        c1, c2 = st.columns([5, 1])
        with c1:
            if st.button(f"📂 {d.replace(st.session_state.current_path, '').rstrip('/')}", key=d, use_container_width=True):
                st.session_state.current_path = d; st.rerun()
        with c2:
            if st.session_state.user_role == "admin" and st.button(t["del"], key=f"del_{d}"):
                get_s3_client().delete_object(Bucket=BUCKET, Key=d); st.rerun()
    for f in f_list:
        if f['Key'] == st.session_state.current_path or f['Key'].endswith('.keep'): continue
        c1, c2, c3 = st.columns([4, 1, 1])
        with c1: st.text(f"📄 {f['Key'].replace(st.session_state.current_path, '')} ({round(f['Size']/1024, 2)} KB)")
        with c2:
            url = get_s3_client().generate_presigned_url('get_object', Params={'Bucket': BUCKET, 'Key': f['Key']}, ExpiresIn=3600)
            st.markdown(f"[⬇️]({url})")
        with c3:
            if st.session_state.user_role == "admin":
                if st.button(t["del"], key=f['Key']): get_s3_client().delete_object(Bucket=BUCKET, Key=f['Key']); st.rerun()
            else: st.button(t["del"], key=f['Key'], disabled=True)

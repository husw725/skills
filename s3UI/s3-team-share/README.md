# S3 Team Share Tool

A lightweight, secure, and multi-language tool for team file sharing via AWS S3.

## 🚀 Quick Start (One-Click)

### Windows Users
Double-click `start.bat`.

### macOS / Linux Users
Run `bash start.sh` in your terminal.

*The script will automatically set up a local Python environment and install necessary dependencies on the first run.*

---

## 🔑 Login & Permissions

- **Admin Account**:
  - **User**: `admin`
  - **Password**: `admin123`
  - **Access**: Full access to `aigc/drama/`. Can Upload, Download, and Delete.

- **Team Account** (Example):
  - **User**: `teamA` (or any username starting with `team`)
  - **Password**: `123`
  - **Access**: Restricted to `aigc/drama/{username}/`. Can Upload and Download only. Delete is disabled.

---

## 🛠 Features
- **Multi-language**: Switch between English and Chinese in the sidebar.
- **Security**: AWS credentials are obfuscated within the code.
- **Zero Configuration**: No need to set up AWS CLI or system environment variables.

---

## 📦 Requirements
- Python 3.8 or higher installed on the system.

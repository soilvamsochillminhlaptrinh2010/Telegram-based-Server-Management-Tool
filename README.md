# Telegram Server Manager

> 🖥️ **Manage and monitor your server directly from Telegram.**
> ⚡ Track electricity usage and costs, 🌍 update electricity prices by country, 🔐 configure remote access, and 🛠️ manage your server without sitting in front of it.

[![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python)](https://www.python.org/)
[![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?logo=telegram)](https://telegram.org/)
[![Linux](https://img.shields.io/badge/Linux-supported-success?logo=linux)](https://www.linux.org/)
[![Windows](https://img.shields.io/badge/Windows-64--bit-blue?logo=windows)](https://www.microsoft.com/windows)

---

## ✨ What is this?

**Telegram Server Manager** is a personal server-management tool that lets you interact with your server through a **Telegram bot**.

Instead of opening a terminal every time, you can send commands through Telegram to monitor your server, check electricity costs, configure remote access, and perform common management tasks.

### Why I made it

I wanted a simple way to manage a home server while being away from it.

The idea was:

```text
                 Telegram
                    │
                    ▼
             ┌─────────────┐
             │  Telegram   │
             │     Bot     │
             └──────┬──────┘
                    │
                    ▼
             ┌─────────────┐
             │ Your Server │
             └─────────────┘
```

No web dashboard is required.
Everything is controlled through Telegram.

---

## 🚀 Features

### 🖥️ Server Management

* Common server management utilities
* Built-in `/help` command
* Execute management actions through Telegram

### ⚡ Electricity Monitoring

* Monitor electricity usage
* Estimate electricity costs
* Automatically update electricity pricing
* Support different electricity prices by country

### 🌐 Remote Access

* Install and configure **ZeroTier**
* Useful when your server is behind a local network
* Includes setup guidance for remote access

### 🖥️ Remote Desktop

* Install **HopToDesk**
* Configure HopToDesk settings through commands

### 🔑 SSH

* SSH setup instructions
* Remote server access support

---

## 📱 Example

The whole system is designed around Telegram commands.

```text
/start
/help
```

The bot provides a list of available commands and guides you through the available server-management features.

> Screenshots and command demonstrations will be added as the project continues to develop.

---

## 💻 Supported Platforms

### Linux

* Ubuntu ✅
* Recommended platform
* Best compatibility

### Windows

* Windows 10 ✅
* 64-bit systems only
* Some SSH-related features may still have limitations

The project has currently been tested on:

* Ubuntu Linux
* Windows 10 64-bit

---

## ⚙️ Installation

Clone the repository:

```bash
git clone https://github.com/soilvamsochillminhlaptrinh2010/Telegram-based-Server-Management-Tool.git
cd Telegram-based-Server-Management-Tool
```

### 1. Configure Telegram

Open:

```text
manager.py
check.py
```

Set:

```python
TOKEN = ""
CHAT_ID = ""
```

* `TOKEN` → your Telegram Bot Token
* `CHAT_ID` → your personal Telegram Chat ID

You can obtain a Telegram Bot Token from **@BotFather**.

---

### 2. Configure Gemini

Set your Gemini API key:

```python
GEMINI_API_KEY = ""
```

Replace it with your own Google Gemini API key.

---

### 3. Run

#### Linux

```bash
./start_linux.sh
```

#### Windows

```text
start_windows.bat
```

---

## ⚠️ Important Notes

Linux is currently the recommended platform.

On Windows, the project works best when the account:

* uses a traditional password instead of a PIN
* is not dependent on a Microsoft-account-only authentication setup

Some SSH functionality may still require additional configuration.

---

## 🔐 Security

This project can perform server-management operations through Telegram.

**Do not expose your bot credentials or API keys.**

Never publish:

```python
TOKEN = "your_real_token"
CHAT_ID = "your_real_chat_id"
GEMINI_API_KEY = "your_real_api_key"
```

Use your own credentials and understand what each command does before running it on a real server.

---

## 🤖 About the Development

This project was developed as a **personal side project during my summer break**.

I'm a Computer Science specialized high school student from the **2025–2028 cohort at Le Quy Don High School for the Gifted – Nam Nha Trang, Khanh Hoa, Vietnam**.

The project took approximately **one month** to develop.

AI tools were used heavily during development. Approximately **70% of the code was generated with Claude**, while I was responsible for:

* designing the project
* deciding the features and architecture
* testing the system
* finding bugs
* debugging and validating the generated code
* integrating the final components

For me, this project was also an experiment in learning how to build a complete system with AI-assisted development.

---

## 🛣️ Roadmap

Possible future improvements:

* [ ] Better server monitoring
* [ ] More detailed electricity statistics
* [ ] More remote-management commands
* [ ] Improved Windows SSH support
* [ ] Better documentation
* [ ] More secure authentication
* [ ] More screenshots and usage examples

---

## 📌 Disclaimer

This project is intended for **educational purposes, personal server management, and research**.

The author is not responsible for damage, data loss, security issues, or misuse resulting from the software.

Use it at your own risk.

---

## ⭐ Support

If you find this project interesting or useful, consider giving it a **star ⭐**.

It helps the project get discovered and motivates further development.

---

### 👨‍💻 Author

Made with curiosity, a home server, and way too much free time.

**Le Quy Don High School for the Gifted – Nam Nha Trang, Vietnam**

# ChangeSense 👁️ // Webpage Change Tracker & Visual Diff Dashboard

A self-contained, lightweight, and modern website change monitoring tool. It crawls pages, filters out noise using CSS selectors, calculates text differences, sends detailed email notifications with visual diff reports, and provides a beautiful dashboard to browse changes.

Supports **two deployment models**:
1. **Local Server / Synology NAS**: Runs as a lightweight local Python web service that handles scheduling and editing monitors in real-time.
2. **100% Serverless GitHub Actions & Pages**: Runs on a cron schedule via GitHub Actions, stores history in the repository, and publishes the dashboard to GitHub Pages. You can add or edit monitored pages directly from the static dashboard using the built-in GitHub REST API integration.

---

## Features
- **Visual Diff Dashboard**: Side-by-side (split) and inline (unified) rendering of text changes, color-coded for readability.
- **HTML Element Focus/Ignore**: Filter out noise (like footers, timestamps, and advertisements) using blacklist selectors, or focus strictly on specific parts of a page using whitelist selectors.
- **Sensitivity Thresholds**: Set sensitivity thresholds to ignore minor changes (presets or custom character thresholds).
- **Email Notifications**: Formatted HTML emails with change summaries and line diff outputs.
- **Double Deployment Ready**: Identical codebase works on local servers, NAS boxes, and GitHub repositories.

---

## 💻 Option 1: Local / Synology NAS Deployment

This deployment utilizes the Flask server (`server.py`) to run a web dashboard and handle background scanning automatically.

### Prerequisites
Make sure you have Python 3.9+ installed.

### 1. Installation
Clone or copy this directory to your machine/NAS and install Python dependencies:
```bash
pip install -r requirements.txt
```

### 2. Run the Web Service
Start the Flask server:
```bash
python server.py
```
Open your browser and navigate to `http://localhost:5000` to access the dashboard.

### 3. Setup Synology NAS Task Scheduler (Alternative to background thread)
If you prefer not to keep a persistent python server running, you can run the Flask server only when you want to look at the dashboard, and configure the Synology Task Scheduler to run the crawls:
1. Open the Synology NAS Control Panel and go to **Task Scheduler**.
2. Click **Create** -> **Scheduled Task** -> **User-defined script**.
3. Set the Task name to `Webpage Crawler` and the user to `root` or your Python user.
4. Set your schedule (e.g., daily or hourly).
5. Under **Run command**, input the path to your python executable and the tracker script:
   ```bash
   cd /volume1/homes/admin/page-tracker
   /usr/local/bin/python3 tracker.py
   ```
6. Click **OK** to save.

---

## 🐙 Option 2: 100% Serverless GitHub Actions & Pages

Run the tracker for free on GitHub infrastructure. No local servers required!

### 1. Push to a Private/Public Repository
Create a new GitHub repository and push this codebase to it:
```bash
git init
git add .
git commit -m "Initial commit of change tracker"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 2. Add Secrets for Email Alerts
To receive email notifications when changes occur, navigate to your repository's **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret** and add:
- `SMTP_HOST` (e.g., `smtp.gmail.com`)
- `SMTP_PORT` (e.g., `587`)
- `SMTP_USER` (e.g., `yourname@gmail.com`)
- `SMTP_PASS` (Your email app password)
- `EMAIL_FROM` (e.g., `yourname@gmail.com`)
- `EMAIL_TO` (e.g., `recipient@domain.com`)
- `SMTP_SECURE` (`true` for SSL/TLS, `false` for STARTTLS)

### 3. Enable GitHub Pages Deployment
1. Go to your repository's **Settings** -> **Pages**.
2. Under **Build and deployment** -> **Source**, select **GitHub Actions** from the dropdown menu (instead of "Deploy from a branch").
3. The workflow is already configured to compile the bundle and publish it automatically.

### 4. How to Manage Monitors on GitHub Pages
Once the GitHub Action runs, it will deploy your static dashboard to `https://YOUR_USERNAME.github.io/YOUR_REPO/`.
To add, edit, or delete websites from this static page:
1. Open your published GitHub Pages URL.
2. Go to the **Settings** panel.
3. Under **GitHub Serverless Mode**, enter:
   - **Repository Path**: `YOUR_USERNAME/YOUR_REPO`
   - **Target Branch**: `main`
   - **Personal Access Token**: Enter a GitHub PAT with `repo` write permissions (this token remains saved safely in your browser's local storage and is never sent to external servers).
4. Click **Activate GitHub Mode**.
5. The dashboard is now connected directly to your repo! Adding or editing a monitor will commit changes directly to `data/monitors.json` in your repository. This will automatically trigger a GitHub Action run within a few seconds to capture the page immediately.

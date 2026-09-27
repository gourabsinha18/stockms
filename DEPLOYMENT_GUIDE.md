# Deployment Guide for StockMS Application

This guide will help you deploy the StockMS Python Flask application to Render.com (free tier) so it's accessible via the internet.

## Prerequisites
1. Git installed on your machine
2. GitHub account (free)
3. Render.com account (free)

## Step 1: Push Code to GitHub

### Option A: Using GitHub Website
1. Go to [github.com](https://github.com) and sign in
2. Click "New" to create a new repository
3. Name it `stockms` (or any name you prefer)
4. Keep it public or private (your choice)
5. Do NOT initialize with README, .gitignore, or license (we already have the code)
6. Click "Create repository"
7. Follow the instructions under "...or push an existing repository from the command line"

### Option B: Using GitHub CLI (if installed)
```bash
# After installing gh CLI and authenticating
gh repo create stockms --public --source=. --remote=origin
```

### Manual Git Commands
```bash
# Add the remote origin (replace USERNAME with your GitHub username)
git remote add origin https://github.com/USERNAME/stockms.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## Step 2: Deploy to Render.com

1. Go to [render.com](https://render.com) and sign up/sign in
2. Click "New +" → "Web Service"
3. Connect your GitHub account if prompted
4. Select the `stockms` repository you just created
5. Configure the service:
   - **Name**: stockms (or your preferred name)
   - **Region**: Choose closest to your users
   - **Branch**: main
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python run.py`
6. Click "Create Web Service"

## Step 3: Wait for Deployment
Render will automatically:
- Clone your repository
- Install dependencies from requirements.txt
- Start your application using the start command
- Provide you with a URL like `https://stockms.onrender.com`

## Step 4: Access Your Application
Once deployment completes (usually 1-2 minutes), you'll see:
- A live URL displayed in your Render dashboard
- Logs showing your application is running
- The application will be accessible at that URL

## Important Notes
- The free tier on Render may spin down after 15 minutes of inactivity
- First request after spin-down may take 10-30 seconds to wake up
- For production use, consider upgrading to a paid plan for always-on instances
- Your application uses port 5000 internally, but Render handles external port mapping

## Troubleshooting
If deployment fails:
1. Check the logs in your Render dashboard
2. Ensure requirements.txt is correctly formatted
3. Verify run.py is in the root directory
4. Check that your application binds to 0.0.0.0 (it does: `host="0.0.0.0"`)

## Database Considerations
The application uses SQLite (stockms.db). On Render's free tier:
- The database will persist during the application's lifetime
- However, if the service is redeployed or restarted, you may lose data
- For persistent storage, consider using Render's PostgreSQL add-on or external database

## URLs You'll Get
After successful deployment, your application will be accessible at:
- `https://stockms.onrender.com` (or similar subdomain)
- Replace "stockms" with whatever name you chose in Render

Enjoy your deployed Python application!
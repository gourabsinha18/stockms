# Deploying Stock Management System on cPanel Web Hosting

This guide will walk you through deploying the Python Flask Stock Management System on a cPanel web hosting account.

## Prerequisites

Before you begin, ensure you have:
1. A cPanel hosting account with Python support
2. SSH access to your cPanel account (recommended for easier setup)
3. The stockms application files (you should have these locally)
4. The CC.sql database file

## Step 1: Prepare Your Application Files

First, organize your application files for upload to cPanel:

1. Create a zip archive of your stockms folder (excluding virtual environment, __pycache__, etc.):
   ```bash
   cd /path/to/your/stockms
   zip -r stockms-deploy.zip * -x "*/__pycache__/*" "*/.pyc" "*/.pyo" "*/.DS_Store" "*/.git/*" "*/.idea/*" "*/.vscode/*" "*/.pytest_cache/*" "*/venv/*" "*/outputs/*"
   ```

2. Log in to your cPanel account and use the File Manager to upload the zip file to your home directory or public_html folder.

3. Extract the uploaded zip file in cPanel File Manager.

## Step 2: Set Up the Python Application in cPanel

1. In cPanel, navigate to **SOFTWARE** → **Setup Python App**

2. Click **+ CREATE APPLICATION**

3. Fill in the form:
   - **Python version**: Choose the latest available (3.8+ recommended)
   - **Application root**: `/home/username/stockms` (or your actual path)
   - **Application URL**: `/stockms` (or leave blank for domain root)
   - **Application startup file**: `passenger_wsgi.py` (we'll create this next)
   - **Application entry point**: `app`

4. Click **Create**

## Step 3: Create the WSGI Entry Point

cPanel uses Passenger to serve Python applications. We need to create a `passenger_wsgi.py` file:

1. In your stockms directory (via cPanel File Manager or SSH), create a new file called `passenger_wsgi.py` with this content:

```python
import sys
import os

# Add the current directory to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Import the Flask app
from app import create_app

# Create the application instance
application = create_app()

# For cPanel/Passenger
if __name__ == "__main__":
    application.run()
```

2. Save the file.

## Step 4: Configure the Database

Your application uses SQLAlchemy and can work with MySQL (common on cPanel). You have a CC.sql file that appears to be a MySQL dump.

### Option A: Using MySQL/MariaDB (Recommended for Production)

1. In cPanel, navigate to **DATABASES** → **MySQL® Databases**

2. Create a new database:
   - Database name: `stockms` (or your preferred name)
   - Click **Create Database**

3. Create a database user:
   - Scroll down to **MySQL® Users**
   - Enter username and password
   - Click **Create User**

4. Add the user to the database:
   - Under **Add User To Database**, select the user and database
   - Click **Add**
   - Select **ALL PRIVILEGES** and click **Make Changes**

5. Import the CC.sql file:
   - Go to **DATABASES** → **phpMyAdmin**
   - Select your newly created database
   - Click the **Import** tab
   - Choose your CC.sql file
   - Set format to SQL
   - Click **Go**

### Option B: Using SQLite (Simpler for Testing)

If you prefer to use SQLite (not recommended for production due to concurrency limitations):

1. The application will automatically create a SQLite database file named `stockms.db` in your application root when you first run it.

2. Skip the MySQL setup above.

## Step 5: Configure Environment Variables

You need to set environment variables for your application:

1. In cPanel Python App manager, click on your created application to manage it.

2. Scroll to **Environment Variables** section.

3. Add these variables:
   - `SECRET_KEY`: A strong random string for Flask session security (generate one using `openssl rand -hex 32`)
   - `DATABASE_URL`: Your database connection string
     - For MySQL: `mysql+pymysql://username:password@localhost/database_name`
     - For SQLite: `sqlite:////home/username/stockms/stockms.db` (full path)
   - `JWT_SECRET_KEY`: Another strong random string for JWT tokens
   - `JWT_COOKIE_SECURE`: Set to `True` if your site uses HTTPS (recommended)
   - `FLASK_ENV`: Set to `production` for production environment

Example MySQL configuration:
```
SECRET_KEY=your_strong_secret_key_here
DATABASE_URL=mysql+pymysql://stockms_user:strong_password@localhost/stockms_db
JWT_SECRET_KEY=another_strong_secret_key_for_jwt
JWT_COOKIE_SECURE=True
FLASK_ENV=production
```

## Step 6: Install Dependencies

1. Still in the Python App manager interface, look for the **Run `pip install`** section.

2. Ensure the requirements.txt file is detected (it should be in your stockms root).

3. Click **Run `pip install`** to install all dependencies from requirements.txt.

4. Wait for the installation to complete. You should see a success message.

## Step 7: Initialize the Database and Seed Data

You need to run the seed script to create tables and initial data:

### Via SSH (Recommended)

If you have SSH access:
1. Connect to your cPanel account via SSH
2. Navigate to your stockms directory: `cd ~/stockms`
3. Activate the virtual environment: `source ./venv/bin/activate`
4. Run the seed script: `python seed.py`
5. If you need to run migrations (for existing databases): `python migrate_employee_stock.py`
6. Deactivate: `deactivate`

### Via cPanel Terminal

If you don't have SSH but cPanel provides a terminal:
1. In cPanel, go to **ADVANCED** → **Terminal**
2. Navigate to your stockms directory: `cd ~/stockms`
3. Activate the virtual environment: `source ./venv/bin/activate`
4. Run the seed script: `python seed.py`
5. Run migrations if needed: `python migrate_employee_stock.py`
6. Deactivate: `deactivate`

### Via Web Interface (Less Ideal)

You can also create a temporary route to initialize the database, but this is less secure and not recommended.

## Step 8: Configure Application Settings

1. In the Python App manager, ensure:
   - **Application started**: Toggle to ON
   - **Application root**: Correct path to your stockms folder
   - **Application URL**: As configured earlier
   - **Application startup file**: `passenger_wsgi.py`
   - **Application entry point**: `app`

2. Click **Save** and then **Restart Application** if needed.

## Step 9: Test Your Application

1. Visit your application URL in a browser (e.g., `https://yourdomain.com/stockms` or just `https://yourdomain.com` if you set it to root).

2. You should see the Stock Management System login page.

3. Login with the default credentials (created by seed.py):
   - Username: `admin`
   - Password: `Admin@12345`
   - **IMPORTANT: Change this password immediately after first login!**

4. Other default users:
   - Stock Manager: `suri_manager` / `Manager@12345`
   - Employee: `suri_employee` / `Employee@12345`

## Step 10: Security Recommendations

For production deployment, please:

1. **Change all default passwords** immediately after first login
2. **Enable HTTPS** (SSL/TLS) for your domain (cPanel has free SSL via Let's Encrypt)
3. **Set strong values** for:
   - `SECRET_KEY`
   - `JWT_SECRET_KEY`
   - Database passwords
4. Consider restricting access to your application if needed (via cPanel IP Deny Manager)
5. Regularly backup your database
6. Monitor application logs for any issues

## Troubleshooting

### Common Issues:

1. **Application fails to start**:
   - Check the application logs in cPanel Python App manager
   - Verify all dependencies are installed correctly
   - Check that your passenger_wsgi.py file is correctly configured

2. **Database connection errors**:
   - Verify your DATABASE_URL is correct
   - Check that the database user has proper permissions
   - Ensure the database server is accessible from your hosting account

3. **Permission errors**:
   - Ensure your application files are readable by the web server
   - The stockms.db file (if using SQLite) must be writable by the web server process

4. **500 Internal Server Error**:
   - Check application logs for specific error details
   - Often caused by missing dependencies or configuration issues

### Getting Help:

If you encounter issues:
1. Check the application logs in the cPanel Python App manager interface
2. Enable debug mode temporarily by setting `FLASK_ENV=development` (remember to disable in production)
3. Consult your hosting provider's support if the issue is server-related

## Maintenance

### Updating Your Application:

1. When you need to update your application:
   - Upload new files via FTP/File Manager (overwrite existing)
   - Run `pip install -r requirements.txt` if dependencies changed
   - Run any new migration scripts
   - Restart the application

### Backing Up:

1. **Database backup**:
   - Use phpMyAdmin to export your database
   - Or use command line: `mysqldump -u username -p database_name > backup.sql`

2. **File backup**:
   - Download your stockms directory via FTP/File Manager
   - Exclude the virtual environment (`venv/`) to save space

## Conclusion

Your Stock Management System should now be running on your cPanel web hosting account! The application is accessible via your domain URL, and you can manage inventory, users, locations, and generate reports as designed.

Remember to:
- Change default passwords immediately
- Keep your application and dependencies updated
- Regularly backup your data
- Monitor for any security advisories related to the packages you're using

For any issues or questions, refer to the application's README.md file or contact your hosting provider's support.
# Running Stock Management System Locally

This guide will help you run the Python Flask Stock Management System on your local machine for testing and development.

## Prerequisites

Before you begin, ensure you have installed:
1. **Python 3.8+** (3.9 or 3.10 recommended)
2. **pip** (Python package manager)
3. **Git** (optional, but useful)
4. **MySQL Server** (if you want to use MySQL) OR you can use SQLite (built into Python)

## Option 1: Using SQLite (Recommended for Local Testing)

This is the easiest option for local development as it requires no additional database setup.

### Step 1: Clone/Copy the Application

If you haven't already, make sure you have the stockms application files in a directory.

### Step 2: Navigate to the Application Directory

```bash
cd /path/to/your/stockms
```

### Step 3: Create a Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Configure for SQLite (Default)

The application is already configured to use SQLite by default. The `config.py` file will create a `stockms.db` file in your application directory when you first run it.

No additional configuration is needed for SQLite!

### Step 6: Initialize the Database and Seed Data

```bash
python seed.py
```

This will:
- Create the SQLite database file (`stockms.db`)
- Create all tables
- Insert sample data (locations, users, product catalog, etc.)

You should see output indicating that locations, admin user, stock manager, employee, and sample product have been created.

### Step 7: Run the Application

```bash
python run.py
```

Or alternatively:
```bash
flask run
```

The application will start on `http://127.0.0.1:5000` (or `http://localhost:5000`)

### Step 8: Access the Application

Open your web browser and go to:
- **URL**: http://127.0.0.1:5000
- **Login with default credentials**:
  - Username: `admin`
  - Password: `Admin@12345`
  
**IMPORTANT: Change this password immediately after first login!**

Other default users:
- Stock Manager: `suri_manager` / `Manager@12345` (access to Suri location only)
- Employee: `suri_employee` / `Employee@12345` (access to Suri location only)

## Option 2: Using MySQL for Local Development

If you prefer to use MySQL locally (closer to production environment):

### Step 1: Install and Start MySQL

Make sure MySQL Server is installed and running on your local machine.
- Download from: https://dev.mysql.com/downloads/mysql/
- Or use a package manager like Homebrew (macOS), apt (Ubuntu), or chocolatey (Windows)

### Step 2: Create a Database and User

Open MySQL command line or use a GUI tool like MySQL Workbench:

```sql
CREATE DATABASE stockms CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'stockms_user'@'localhost' IDENTIFIED BY 'your_strong_password';
GRANT ALL PRIVILEGES ON stockms.* TO 'stockms_user'@'localhost';
FLUSH PRIVILEGES;
```

### Step 3: Import the CC.sql File

You have a CC.sql file which is a MySQL dump. Import it:

```bash
# Using command line:
mysql -u stockms_user -p stockms < CC.sql

# Or using MySQL Workbench:
# Server → Data Import → Import from Self-Contained File
```

### Step 4: Configure Environment Variables

You need to tell the application to use MySQL instead of SQLite. Set the DATABASE_URL environment variable:

#### Windows (Command Prompt):
```cmd
set DATABASE_URL=mysql+pymysql://stockms_user:your_strong_password@localhost/stockms
```

#### Windows (PowerShell):
```powershell
$env:DATABASE_URL="mysql+pymysql://stockms_user:your_strong_password@localhost/stockms"
```

#### macOS/Linux:
```bash
export DATABASE_URL="mysql+pymysql://stockms_user:your_strong_password@localhost/stockms"
```

You may also want to set a strong SECRET_KEY:
```bash
# Generate a secret key (run this and copy the output)
python -c "import secrets; print(secrets.token_hex(32))"

# Then set it:
# Windows (Command Prompt):
set SECRET_KEY=your_generated_secret_key_here
# macOS/Linux:
export SECRET_KEY=your_generated_secret_key_here
```

### Step 5: Create Virtual Environment and Install Dependencies

Same as Option 1, Steps 2-4:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

### Step 6: Run Migration Script (if needed)

If you imported the CC.sql file, your database should already have tables. However, you may need to run the migration script for the employee stock features:

```bash
python migrate_employee_stock.py
```

### Step 7: Run the Application

```bash
python run.py
```

### Step 8: Access the Application

Same as Option 1, Step 8.

## Troubleshooting Local Setup

### Common Issues:

1. **ModuleNotFoundError: No module named 'flask'**
   - Make sure you activated your virtual environment
   - Run `pip install -r requirements.txt` again

2. **Database connection errors**
   - For MySQL: Verify MySQL is running, credentials are correct, and database exists
   - For SQLite: Check file permissions in your application directory

3. **Address already in use**
   - Another application is using port 5000
   - Either stop the other application or change the port in run.py:
     ```python
     app.run(debug=True, host="0.0.0.0", port=5001)  # Change 5000 to another port
     ```

4. **Missing dependencies**
   - Run `pip install -r requirements.txt --upgrade`

### Resetting the Database:

If you want to start fresh:
1. For SQLite: Delete the `stockms.db` file
2. For MySQL: Drop and recreate the database, then re-import CC.sql
3. Run `python seed.py` again

## Next Steps After Local Testing

Once you've verified the application works locally:
1. Explore the features: stock operations, reports, user management, etc.
2. Make any necessary changes or customizations
3. When ready for production, follow the cPanel deployment guide
4. Remember to use strong passwords and proper security practices in production

## Application Structure Overview

```
stockms/
├── app/                    # Main application package
│   ├── __init__.py         # Application factory and setup
│   ├── models.py           # Database models
│   ├── extensions.py       # Flask extensions (db, login, etc.)
│   ├── services/           # Business logic services
│   ├── blueprints/         # Application modules (auth, stock, reports, etc.)
│   ├── templates/          # HTML templates
│   └── static/             # CSS, JavaScript, images
├── migrations/             # Database migration scripts (if using Flask-Migrate)
├── tests/                  # Unit tests
├── requirements.txt        # Python dependencies
├── config.py               # Configuration settings
├── run.py                  # Development server entrypoint
├── seed.py                 # Database initialization with sample data
├── migrate_employee_stock.py  # Migration for employee stock features
└── CC.sql                  # MySQL database dump
```

## Important Security Notes for Local Testing:

1. **Default passwords are weak** - change them immediately in a real environment
2. **Debug mode is enabled** - never use debug=True in production
3. **SECRET_KEY should be strong and secret** - generate a random one for production
4. **Database credentials should be secured** - never commit them to version control

Enjoy testing your Stock Management System locally!
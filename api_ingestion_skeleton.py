import snowflake.connector
import requests
import json
import os
import tempfile
import getpass

# 1. Configure the API URL and stage name here or override before running
#    Replace the empty strings with your API endpoint and stage when you test.
API_URL = ""  # e.g. "https://api.example.com/data" (leave blank for students to supply)
SNOWFLAKE_USER = ""  # e.g. Your account identifier
DATABASE = ""
SCHEMA = ""
STAGE_NAME = ""  # e.g. "my_internal_stage"

def stage_api_data():
    """Main pipeline function: extract -> save -> connect -> stage -> cleanup.

    Instructions for students (in comments below):
      - Set `API_URL` to the REST endpoint that returns JSON, or pass it in code.
      - Set `STAGE_NAME` to your Snowflake internal stage (create it in Snowflake first).
      - Provide Snowflake credentials via environment variables or prompt when asked.
      - After PUT, run a `COPY INTO` (optional) command in Snowflake to load staged files into a table.
    """
    
    if not API_URL:
        print("API_URL is not set. Please update API_URL in the script before running.")
        return
    if not STAGE_NAME:
        print("STAGE_NAME is not set. Please update STAGE_NAME in the script before running.")
        return
    
    # 2. Extract: Pull data from the REST API
    print(f"Fetching data from {API_URL}...")
    try:
        response = requests.get(API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Failed to fetch API data: {e}")
        return
    
    data = response.json()

    # 3. Save payload to a temporary local file
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, "api_payload.json")
    
    with open(file_path, 'w') as f:
        json.dump(data, f)
    
    print(f"Data saved locally to {file_path}")

    # 4. Securely prompt for the password in the terminal (keystrokes will be hidden)
    snf_password = getpass.getpass("Enter your Snowflake password: ")

    print("Connecting to Snowflake...")
    # We keep the connection_name so it knows your account/user, but we inject the password securely
    conn = snowflake.connector.connect(
        connection_name=SNOWFLAKE_USER,
        password=snf_password
    )
    
    try:
        cursor = conn.cursor()

        # 5. Context Setup (Ensure we are in the right database/schema)
        cursor.execute(f"USE DATABASE {DATABASE};")
        cursor.execute(f"USE SCHEMA {SCHEMA};")

        # 6. Stage: Push the local file to the Snowflake Internal Stage
        print("Uploading file to internal stage...")
        put_query = f"PUT file://{file_path} @{STAGE_NAME} AUTO_COMPRESS=FALSE OVERWRITE=TRUE;"
        cursor.execute(put_query)

        print("Success! Data is now sitting securely in your Snowflake Internal Stage.")
        print("Next step: Use Snowflake to inspect the stage and write your COPY INTO command.")

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        # 7. Cleanup
        cursor.close()
        conn.close()
        if os.path.exists(file_path):
            os.remove(file_path)
            print("Temporary local file cleaned up.")

if __name__ == "__main__":
    stage_api_data()
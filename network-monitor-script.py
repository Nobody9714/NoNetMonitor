import sys
import subprocess
import pkg_resources
import speedtest
import time
import csv
from datetime import datetime, timedelta
import schedule
import os
import pandas as pd
import plotly.express as px
from flask import Flask, render_template, request, jsonify
from threading import Thread
import socket
from requests.exceptions import RequestException

def check_and_install_dependencies():
    required = {'speedtest-cli', 'schedule', 'flask', 'pandas', 'plotly'}
    installed = {pkg.key for pkg in pkg_resources.working_set}
    missing = required - installed

    if missing:
        print("The following dependencies are missing:")
        for pkg in missing:
            print(f"  - {pkg}")
        
        install = input("Do you want to install these dependencies? (y/n): ").lower().strip()
        if install == 'y':
            python = sys.executable
            subprocess.check_call([python, '-m', 'pip', 'install', *missing], stdout=subprocess.DEVNULL)
            print("Dependencies installed successfully.")
        else:
            print("Please install the missing dependencies manually and run the script again.")
            sys.exit(1)

# Run dependency check
check_and_install_dependencies()

app = Flask(__name__)

def get_ip_address():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def run_speed_test():
    try:
        print("Initializing Speedtest...")
        st = speedtest.Speedtest()
        print("Getting best server...")
        st.get_best_server()
        
        print("Testing download speed...")
        download_speed = st.download() / 1_000_000  # Convert to Mbps
        print(f"Download speed: {download_speed:.2f} Mbps")
        
        print("Testing upload speed...")
        upload_speed = st.upload() / 1_000_000  # Convert to Mbps
        print(f"Upload speed: {upload_speed:.2f} Mbps")
        
        print("Getting ping...")
        ping = st.results.ping
        print(f"Ping: {ping:.2f} ms")
        
        server = st.results.server['sponsor'] + " (" + st.results.server['name'] + ", " + st.results.server['country'] + ")"
        print(f"Server: {server}")
        
        return download_speed, upload_speed, ping, server
    except speedtest.ConfigRetrievalError as e:
        print(f"ConfigRetrievalError: {str(e)}")
        print("Unable to retrieve speedtest.net configuration. Check your internet connection.")
        raise
    except speedtest.NoMatchedServers as e:
        print(f"NoMatchedServers: {str(e)}")
        print("No matched servers: Unable to find a suitable speedtest.net server.")
        raise
    except speedtest.SpeedtestBestServerFailure as e:
        print(f"SpeedtestBestServerFailure: {str(e)}")
        print("Unable to connect to servers to test latency. Check your firewall settings.")
        raise
    except RequestException as e:
        print(f"RequestException: {str(e)}")
        print(f"Network error occurred: {str(e)}")
        raise
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        print(f"An unexpected error occurred: {str(e)}")
        raise

def log_results(download, upload, ping, server):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file = "network_log.csv"
    
    if not os.path.exists(log_file):
        with open(log_file, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Download (Mbps)", "Upload (Mbps)", "Ping (ms)", "Server"])
    
    with open(log_file, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([timestamp, f"{download:.2f}", f"{upload:.2f}", f"{ping:.2f}", server])
    
    print(f"Logged results at {timestamp}")

def run_and_log():
    try:
        download, upload, ping, server = run_speed_test()
        log_results(download, upload, ping, server)
    except Exception as e:
        print(f"An error occurred: {e}")

@app.route('/')
def index():
    interval = request.args.get('interval', '60')  # Default to 60 minutes
    df = pd.read_csv('network_log.csv')
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    
    # Define time intervals
    intervals = {
        '15': timedelta(minutes=15),
        '30': timedelta(minutes=30),
        '60': timedelta(hours=1),
        '360': timedelta(hours=6),
        '720': timedelta(hours=12),
        '1440': timedelta(days=1),
        '4320': timedelta(days=3),
        '7200': timedelta(days=5),
        '10080': timedelta(days=7),
        '20160': timedelta(days=14),
        '43200': timedelta(days=30),
        '86400': timedelta(days=60),
        '129600': timedelta(days=90),
        '172800': timedelta(days=120),
        '525600': timedelta(days=365),
        '1051200': timedelta(days=730)
    }
    
    # Filter data based on the selected time interval
    now = pd.Timestamp.now()
    start_time = now - intervals[interval]
    
    df = df[df['Timestamp'] > start_time]
    
    # Get the last test results
    last_test = df.iloc[-1] if not df.empty else None
    
    # Calculate averages for the last 24 hours
    last_24h = now - timedelta(hours=24)
    df_24h = df[df['Timestamp'] > last_24h]
    avg_24h = {
        'download': df_24h['Download (Mbps)'].mean(),
        'upload': df_24h['Upload (Mbps)'].mean(),
        'ping': df_24h['Ping (ms)'].mean()
    }
    
    def set_y_range(values, buffer_percent=10):
        if len(values) == 0:
            return [0, 1]  # Default range if no data
        min_val = min(values)
        max_val = max(values)
        range_buffer = (max_val - min_val) * (buffer_percent / 100)
        return [max(0, min_val - range_buffer), max_val + range_buffer]

    def create_graph(df, y_column, title):
        fig = px.line(df, x='Timestamp', y=y_column, title=title)
        fig.update_layout(
            yaxis_range=set_y_range(df[y_column]),
            xaxis_range=[start_time, now],
            xaxis_tickformat='%Y-%m-%d %H:%M' if interval in ['43200', '86400', '129600', '172800', '525600', '1051200'] else '%H:%M',
            xaxis_title="Time"
        )
        return fig.to_html(full_html=False)

    graphs = [
        create_graph(df, 'Download (Mbps)', 'Download Speed Over Time'),
        create_graph(df, 'Upload (Mbps)', 'Upload Speed Over Time'),
        create_graph(df, 'Ping (ms)', 'Latency Over Time')
    ]
    
    return render_template('index.html', graphs=graphs, selected_interval=interval, last_test=last_test, avg_24h=avg_24h)

@app.route('/run-test', methods=['POST'])
def run_test():
    try:
        download, upload, ping, server = run_speed_test()
        log_results(download, upload, ping, server)
        return jsonify({
            'success': True,
            'message': 'Speed test completed successfully',
            'data': {
                'download': f"{download:.2f}",
                'upload': f"{upload:.2f}",
                'ping': f"{ping:.2f}",
                'server': server
            }
        }), 200
    except Exception as e:
        error_message = str(e)
        print(f"Error during speed test: {error_message}")
        return jsonify({
            'success': False,
            'message': f'An error occurred: {error_message}'
        }), 500

def run_flask():
    ip_address = get_ip_address()
    print(f"Web interface available at: http://{ip_address}:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

def run_scheduler():
    schedule.every().hour.at(":00").do(run_and_log)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    # Check if the templates directory and index.html exist
    if not os.path.exists('templates/index.html'):
        print("Error: templates/index.html not found.")
        print("Please ensure you have created the 'templates' directory and added the index.html file.")
        sys.exit(1)

    # Run the initial speed test
    run_and_log()
    
    # Start the Flask server in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    # Run the scheduler in the main thread
    run_scheduler()

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app  # noqa: E402
from app.config import DATA_DIR, HOST, PORT  # noqa: E402

app = create_app()

if __name__ == "__main__":
    print(f"数据目录：{DATA_DIR}", flush=True)
    print(f"访问地址：http://<NAS_IP>:{PORT}", flush=True)
    try:
        from waitress import serve

        serve(app, host=HOST, port=PORT, threads=10)
    except ImportError:
        app.run(host=HOST, port=PORT, threaded=True)

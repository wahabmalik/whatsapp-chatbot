import os
import platform

from wsgi import app


def serve() -> None:
    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))

    if platform.system().lower().startswith("win"):
        from waitress import serve as waitress_serve

        threads = int(os.getenv("WAITRESS_THREADS", "8"))
        waitress_serve(app, host=host, port=port, threads=threads)
        return

    # Keep Gunicorn as the primary production server on Unix-like hosts.
    os.execvp("gunicorn", ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"])


if __name__ == "__main__":
    serve()

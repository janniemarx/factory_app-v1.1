from v2.app import create_app

app = create_app()

# For local dev via waitress:
# waitress-serve --host=0.0.0.0 --port=8081 v2.wsgi_v2:app

# Eventlet monkey patching MUST be first, before any other imports
import eventlet
eventlet.monkey_patch()

from app import create_app

app = create_app()

if __name__ == '__main__':
    # Use use_reloader=False to prevent double initialization
    app.run(debug=False, host='0.0.0.0', port=8000, use_reloader=False)
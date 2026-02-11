from flask import Blueprint

api_bp = Blueprint('api_v2', __name__)

@api_bp.route('/health')
def health():
    return {"status": "ok"}

from flask import Flask, request, jsonify, make_response
import base64, io, os

app = Flask(__name__)

# Increase max content length to 50MB
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

def corsify(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = '*'
    return response

@app.route('/', methods=['GET'])
def index():
    return corsify(make_response(jsonify({'status': 'ok'})))

@app.route('/health', methods=['GET'])
def health():
    return corsify(make_response(jsonify({'status': 'ok'})))

@app.route('/process', methods=['POST', 'OPTIONS'])
def process():
    if request.method == 'OPTIONS':
        return corsify(make_response('', 200))
    try:
        data = request.get_json(force=True, silent=True)
        if not data or 'pdf' not in data:
            return corsify(make_response(jsonify({'error': 'No PDF data received'}), 400))
        
        # Fix base64 padding if needed
        b64 = data['pdf']
        b64 += '=' * (4 - len(b64) % 4) if len(b64) % 4 else ''
        pdf_bytes = base64.b64decode(b64)
        
        if len(pdf_bytes) < 100:
            return corsify(make_response(jsonify({'error': 'PDF too small, likely corrupted'}), 400))
        
        from processor import process_profile
        result = process_profile(io.BytesIO(pdf_bytes))
        
        resp = make_response(jsonify({'pdf': base64.b64encode(result).decode()}))
        return corsify(resp)
    except Exception as e:
        import traceback
        traceback.print_exc()
        resp = make_response(jsonify({'error': str(e)}), 500)
        return corsify(resp)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

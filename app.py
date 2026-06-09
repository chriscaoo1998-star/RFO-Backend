from flask import Flask, request, jsonify
import base64, io, os, sys

app = Flask(__name__)

# Allow CORS from anywhere
@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/process', methods=['OPTIONS', 'POST'])
def process():
    if request.method == 'OPTIONS':
        return '', 200
    try:
        data = request.get_json()
        pdf_bytes = base64.b64decode(data['pdf'])
        from processor import process_profile
        result = process_profile(io.BytesIO(pdf_bytes))
        return jsonify({'pdf': base64.b64encode(result).decode()})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5050))
    app.run(host='0.0.0.0', port=port)

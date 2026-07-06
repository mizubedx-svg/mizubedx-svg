from flask import Flask, render_template, request, send_file, make_response
import pandas as pd
import io
import zipfile
from mizubedx import report_generator, external_data

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        file = request.files.get("file")
        if not file: return "ファイルなし", 400
        
        df = pd.read_csv(file)
        
        # ZIPファイルにまとめる準備
        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w') as zf:
            for i, row in df.iterrows():
                # ここで各エリアごとのPDF生成
                # (既存のレポート生成ロジックを呼び出し)
                pdf_bytes = report_generator.render_report_pdf(
                    observation={"area": row["【最重要】観測エリアを選択してください"], ...},
                    # ... CSVの列データから必要な値をセット ...
                )
                zf.writestr(f"report_{i}.pdf", pdf_bytes)
        
        memory_file.seek(0)
        return send_file(memory_file, download_name="reports.zip", as_attachment=True)
    
    return '''
        <form method="post" enctype="multipart/form-data">
            <input type="file" name="file">
            <button type="submit">PDF一括作成(ZIP)</button>
        </form>
    '''

if __name__ == "__main__":
    app.run(port=5001) # 別のポートで起動
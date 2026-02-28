# excel-writer

用 JSON/CSV/Markdown 表格生成或更新 Excel（.xlsx）。

## 依赖
- python3
- openpyxl（若缺失：`python3 -m pip install --user openpyxl`）

## 用法
脚本位置：`~/.gpt-cli/skills/excel-writer/scripts/write_excel.py`

### 1) JSON 写入（覆盖创建）
```bash
cat > data.json <<'JSON'
[
  {"name": "Alice", "score": 95},
  {"name": "Bob", "score": 88, "remark": "good"}
]
JSON

python3 ~/.gpt-cli/skills/excel-writer/scripts/write_excel.py \
  --out ./output.xlsx --sheet Sheet1 --mode overwrite --format json --input data.json
```

### 2) CSV 追加到现有表
```bash
python3 ~/.gpt-cli/skills/excel-writer/scripts/write_excel.py \
  --out ./output.xlsx --sheet Sheet1 --mode append --format csv --input - <<'CSV'
name,score
Carol,77
CSV
```

### 3) Markdown 表格写入
```bash
python3 ~/.gpt-cli/skills/excel-writer/scripts/write_excel.py \
  --out ./table.xlsx --sheet 数据 --mode overwrite --format md --input - <<'MDT'
| name | score |
| --- | --- |
| Dan | 90 |
MDT
```

## 模式说明
- `overwrite`：覆盖生成一个新 xlsx
- `append`：对指定 sheet 追加行（不存在则新建）
- `replace_sheet`：删除并重建指定 sheet

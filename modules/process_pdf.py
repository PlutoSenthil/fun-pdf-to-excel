
import pdfplumber

def process_pdf(input_file_path, output_file_path):
    result = []
    index = 0
    with pdfplumber.open(input_file_path) as pdf, open(output_file_path, 'w', encoding='utf-8') as outfile:
        outfile.write(input_file_path + '\n')
        for page_num, page in enumerate(pdf.pages, start=1):
            table = page.extract_table()
            if table:
                column_len = len(table)
                for i, row in zip(range(column_len), table):
                    row_len = len(row)
                    if i == 0:
                        prt_str = f"#--------- Page:{page_num} Rows:{row_len} Columns:{column_len} --------#"
                        outfile.write(prt_str + '\n')
                    # cleaned_row = [element for element in row if element is not None and element != '']
                    cleaned_row = [element for element in row]
                    outfile.write(str(index) + '|')
                    index=index+1
                    if cleaned_row:
                        result.append(cleaned_row)
                        line = str(cleaned_row)
                        outfile.write(line + '\n')
            else:
                prt_str = f"#--------- Page:{page_num} No table found on this page. --------#"
                outfile.write(prt_str + '\n')
    return result

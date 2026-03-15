import streamlit as st
import fitz
import re
import pandas as pd
import altair as alt

st.set_page_config(page_title="NIMCET Marks Checker", page_icon="🎓", layout="wide")

st.title("🎓 ACME Academy | NIMCET Marks Checker")

uploaded_file = st.file_uploader("Upload NIMCET Response Sheet", type=["pdf"])


# ---------- Candidate Details ----------

def extract_candidate_info(text):

    app_no = None
    name = None

    app_match = re.search(r"Application Seq No\s*(\S+)", text)
    name_match = re.search(r"Candidate Name\s*([A-Za-z\s]+?)\s*TC Name", text)

    if app_match:
        app_no = app_match.group(1)

    if name_match:
        name = name_match.group(1).strip()

    return app_no, name


# ---------- Parse Questions from PDF ----------

def parse_nimcet_pdf(file_bytes):

    doc = fitz.open(stream=file_bytes, filetype="pdf")

    all_markers = []
    lines_info = []

    for page_num, page in enumerate(doc):
        page_height = page.rect.height
        y_offset = page_num * page_height

        drawings = page.get_drawings()
        for d in drawings:
            rect = d["rect"]
            for c_key in ("color", "fill"):
                c = d.get(c_key)
                if isinstance(c, (list, tuple)) and len(c) >= 3:
                    r, g, b = c[:3]
                    if r > 1: r, g, b = r/255.0, g/255.0, b/255.0
                    
                    if g > r + 0.1 and g > b + 0.1:
                        all_markers.append({"abs_y": y_offset + rect.y0, "type": "green"})
                    elif r > g + 0.1 and r > b + 0.1:
                        all_markers.append({"abs_y": y_offset + rect.y0, "type": "red"})

        dicts = page.get_text("dict")["blocks"]
        for block in dicts:
            if "lines" not in block: continue
            for line in block["lines"]:
                line_text = ""
                for span in line["spans"]:
                    text = span["text"].strip()
                    line_text += " " + text
                    
                    color_int = span["color"]
                    rect = fitz.Rect(span["bbox"])
                    abs_y_span = y_offset + rect.y0
                    
                    r = ((color_int >> 16) & 255) / 255.0
                    g = ((color_int >> 8) & 255) / 255.0
                    b = (color_int & 255) / 255.0
                    
                    if "✔" in text:
                        all_markers.append({"abs_y": abs_y_span, "type": "green"})
                    elif "✘" in text:
                        all_markers.append({"abs_y": abs_y_span, "type": "red"})
                    elif (g > r + 0.1 and g > b + 0.1) and text:
                        all_markers.append({"abs_y": abs_y_span, "type": "green"})
                    elif (r > g + 0.1 and r > b + 0.1) and text:
                        all_markers.append({"abs_y": abs_y_span, "type": "red"})

                rect = fitz.Rect(line["bbox"])
                abs_y = y_offset + rect.y0
                lines_info.append({"text": line_text.strip(), "abs_y": abs_y})

    all_markers.sort(key=lambda x: x["abs_y"])
    merged_markers = []
    for m in all_markers:
        if not merged_markers:
            merged_markers.append(m)
        else:
            last = merged_markers[-1]
            if last["type"] == m["type"] and abs(last["abs_y"] - m["abs_y"]) < 10:
                pass
            else:
                merged_markers.append(m)

    questions_meta = []
    current_q = None
    
    for line in lines_info:
        text = line["text"]
        abs_y = line["abs_y"]
        
        match_qid = re.search(r"Question ID\s*:\s*(\d+)", text)
        if match_qid:
            current_q = {
                "qid": match_qid.group(1),
                "chosen": None,
                "correct": None,
                "abs_y": abs_y,
                "markers": []
            }
            questions_meta.append(current_q)
            
        if current_q and "Chosen Option" in text:
            match_cho = re.search(r"Chosen Option\s*:\s*(\d+|--)", text)
            if match_cho:
                current_q["chosen"] = match_cho.group(1)

    questions_meta.sort(key=lambda x: x["abs_y"])
    
    for m in merged_markers:
        for q in questions_meta:
            if q["abs_y"] > m["abs_y"] - 10:
                q["markers"].append(m)
                break

    for q in questions_meta:
        marks = sorted(q["markers"], key=lambda x: x["abs_y"])
        
        if len(marks) > 4:
            marks = marks[-4:]
            
        green_indices = [i + 1 for i, m in enumerate(marks) if m["type"] == "green"]
        
        if green_indices:
            q["correct"] = str(green_indices[0])

    return questions_meta


# ---------- Score Calculation ----------

def calculate_score(data):

    stats = {
        "Math": {"correct": 0, "wrong": 0, "unattempted": 0, "score": 0},
        "LR": {"correct": 0, "wrong": 0, "unattempted": 0, "score": 0},
        "Computer": {"correct": 0, "wrong": 0, "unattempted": 0, "score": 0},
        "English": {"correct": 0, "wrong": 0, "unattempted": 0, "score": 0},
    }

    for i, q in enumerate(data):
        chosen = q["chosen"]
        correct = q["correct"]

        if i < 50:
            sec = "Math"
        elif i < 90:
            sec = "LR"
        elif i < 110:
            sec = "Computer"
        else:
            sec = "English"

        if chosen == "--" or chosen is None:
            stats[sec]["unattempted"] += 1
            continue

        if chosen == correct:
            stats[sec]["correct"] += 1
        else:
            stats[sec]["wrong"] += 1

    stats["Math"]["score"] = stats["Math"]["correct"] * 12 - stats["Math"]["wrong"] * 3
    stats["LR"]["score"] = stats["LR"]["correct"] * 6 - stats["LR"]["wrong"] * 1.5
    stats["Computer"]["score"] = stats["Computer"]["correct"] * 6 - stats["Computer"]["wrong"] * 1.5
    stats["English"]["score"] = stats["English"]["correct"] * 4 - stats["English"]["wrong"] * 1

    total = stats["Math"]["score"] + stats["LR"]["score"] + stats["Computer"]["score"] + stats["English"]["score"]

    return stats, total


# ---------- MAIN ----------

if uploaded_file:

    with st.spinner("Processing response sheet..."):

        pdf_bytes = uploaded_file.read()

        text = ""

        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                text += page.get_text()

        app_no, name = extract_candidate_info(text)

        questions = parse_nimcet_pdf(pdf_bytes)

        stats, total = calculate_score(questions)


        st.subheader("Candidate Details")

        st.write("Application No:", app_no)
        st.write("Name:", name)


        st.subheader("Performance Summary")

        col1, col2, col3, col4, col5 = st.columns(5)

        total_correct = sum(s["correct"] for s in stats.values())
        total_wrong = sum(s["wrong"] for s in stats.values())
        total_unattempted = sum(s["unattempted"] for s in stats.values())

        col1.metric("Total Score", total, delta_color="off")
        col2.metric("Total Correct", total_correct)
        col3.metric("Total Wrong", total_wrong)
        col4.metric("Unattempted", total_unattempted)

        st.subheader("Section-wise Breakdown")

        df_stats = pd.DataFrame([
            {"Section": "Mathematics", "Correct": stats["Math"]["correct"], "Wrong": stats["Math"]["wrong"], "Unattempted": stats["Math"]["unattempted"], "Score": stats["Math"]["score"]},
            {"Section": "Logical Reasoning", "Correct": stats["LR"]["correct"], "Wrong": stats["LR"]["wrong"], "Unattempted": stats["LR"]["unattempted"], "Score": stats["LR"]["score"]},
            {"Section": "Computer Awareness", "Correct": stats["Computer"]["correct"], "Wrong": stats["Computer"]["wrong"], "Unattempted": stats["Computer"]["unattempted"], "Score": stats["Computer"]["score"]},
            {"Section": "General English", "Correct": stats["English"]["correct"], "Wrong": stats["English"]["wrong"], "Unattempted": stats["English"]["unattempted"], "Score": stats["English"]["score"]}
        ])

        st.dataframe(df_stats, use_container_width=True, hide_index=True)

        chart_data = pd.DataFrame({
            "Section": ["Math", "Logical Reasoning", "Computer Awareness", "General English"],
            "Score": [stats["Math"]["score"], stats["LR"]["score"], stats["Computer"]["score"], stats["English"]["score"]]
        })

        chart = alt.Chart(chart_data).mark_bar().encode(
            x=alt.X("Section", sort=None),
            y="Score",
            color=alt.Color("Section", legend=None),
            tooltip=["Section", "Score"]
        ).properties(height=300)

        st.altair_chart(chart, use_container_width=True)

        st.subheader("Question-wise Analysis")

        q_rows = []
        for i, q in enumerate(questions):
            status = "Unattempted"
            marks = 0

            chosen = q["chosen"]
            correct = q["correct"]

            if i < 50:
                pos_m, neg_m = 12, -3
                sec = "Math"
            elif i < 90:
                pos_m, neg_m = 6, -1.5
                sec = "LR"
            elif i < 110:
                pos_m, neg_m = 6, -1.5
                sec = "Computer"
            else:
                pos_m, neg_m = 4, -1
                sec = "English"

            if chosen and chosen != "--":
                if chosen == correct:
                    status = "Correct"
                    marks = pos_m
                else:
                    status = "Incorrect"
                    marks = neg_m

            q_rows.append({
                "Q. No": i + 1,
                "Question ID": q.get("qid", "N/A"),
                "Section": sec,
                "Chosen Option": q.get("chosen", "--"),
                "Correct Option": q.get("correct", "Unknown"),
                "Status": status,
                "Marks": marks
            })

        st.dataframe(pd.DataFrame(q_rows), use_container_width=True, hide_index=True)

        st.success("Marks calculated successfully!")
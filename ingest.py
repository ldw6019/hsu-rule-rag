"""data/raw/*.html 공지를 읽어 청크로 자르고 data/chunks.jsonl로 저장한다.

실행: python ingest.py
"""
import json
from pathlib import Path

from bs4 import BeautifulSoup

RAW_DIR = Path("data/raw")
OUT_PATH = Path("data/chunks.jsonl")
URL = "https://www.hansung.ac.kr/bbs/hansung/2127/{}/artclView.do"


def load_documents(raw_dir):
    """폴더의 공지 HTML을 읽어 문서 리스트를 반환한다.

    반환: [{"doc_id": "223607", "source": URL, "title": "...", "text": "본문"}, ...]
    """
    docs = []
    for path in sorted(raw_dir.glob("*.html")):
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        title = soup.select_one(".view.viewCont .title strong").get_text(strip=True)
        body = soup.select_one(".view.viewCont .txt")
        # 이 게시판은 글자 중간이 <span>으로 쪼개져 있다.
        # 본문 전체에 get_text(" ")를 하면 "2026학년 도 2 학 기"처럼 깨지므로,
        # <p>마다 구분자 없이 get_text() 하고 줄바꿈으로 잇는다. (표 안의 칸도 <p>라서 같이 들어온다)
        lines = [p.get_text() for p in body.find_all("p")]
        docs.append({
            "doc_id": path.stem,
            "source": URL.format(path.stem),
            "title": title,
            "text": "\n".join(lines),
        })
    return docs


def clean(text):
    """본문 텍스트를 정리한다. 줄바꿈은 남겨 둔다 (split_chunks가 줄 단위로 쓸 수 있게).

    하는 일:
      1. "\\xa0"(HTML의 &nbsp;)을 보통 공백 " "으로 바꾸기
         - 이유: 눈에는 같은 공백이지만 다른 글자라서, 그대로 두면 검색·비교가 어긋난다.
      2. 줄마다 앞뒤 공백 지우기
         - 이유: <p> 안의 들여쓰기 공백이 청크 글자 수만 늘린다.
      3. 빈 줄 지우기
         - 이유: 빈 <p>가 많아서(문서당 10~40줄) 남겨 두면 청크에 빈칸만 쌓인다.
    """
    # 1. &nbsp; → 보통 공백
    text = text.replace("\xa0", " ")

    result = []
    for line in text.split("\n"):
        # 2. 줄 앞뒤 공백 지우기
        line = line.strip()
        # 3. 빈 줄은 버리기
        if line != "":
            result.append(line)
    return "\n".join(result)


def is_heading(line):
    """'1. 휴학 신청 안내'처럼 큰 번호로 시작하는 줄이면 True를 돌려준다.

    '2026. 7. 27.'이나 '26. 9. 9.(수)' 같은 날짜 줄은 제목이 아니므로 False.
    """
    dot = line.find(". ")
    if dot == -1:                      # ". "이 없으면 번호 줄이 아님
        return False

    number = line[:dot]                # ". " 앞부분 (예: "1", "2026")
    rest = line[dot + 2:].strip()      # ". " 뒷부분 (예: "휴학 신청 안내", "7. 27.")

    # 앞부분이 0~9 숫자가 아니면 아님 (isdigit()은 "①"도 숫자로 봐서 isdecimal()을 씀)
    if not number.isdecimal():
        return False
    if len(number) > 2:                # "2026."처럼 숫자가 3자리 이상이면 연도
        return False
    if rest == "" or rest[0].isdigit():  # "26. 9. 9."처럼 뒤가 또 숫자면 날짜
        return False
    return True


def pack_lines(lines, max_chars):
    """A 방식: 줄을 차례로 붙이다가 max_chars를 넘기 직전에 끊는다.

    줄 하나가 max_chars보다 길면 그 줄은 자르지 않고 그대로 한 청크가 된다.
    """
    chunks = []
    current = ""  # 지금 만들고 있는 청크

    for line in lines:
        if current == "":
            current = line                        # 비어 있으면 그냥 넣기
        elif len(current) + 1 + len(line) <= max_chars:
            current = current + "\n" + line       # 붙여도 안 넘치면 붙이기
        else:
            chunks.append(current)                # 넘치면 지금 청크를 저장하고
            current = line                        # 새 청크를 시작

    if current != "":
        chunks.append(current)                    # 마지막 청크도 저장
    return chunks


def split_chunks(text, max_chars=500):
    """텍스트 하나를 청크 문자열 리스트로 자른다.

    방식 후보:
      A. 글자 수: 줄을 차례로 붙이다가 max_chars를 넘기 직전에 끊기
      B. 번호 단위: "1. ", "2. "처럼 큰 번호로 시작하는 줄에서 끊고,
         그래도 max_chars보다 긴 덩어리만 A 방식으로 다시 끊기

    선택: B (번호 단위)
      이유 1. 공지가 "1. 휴학 신청 안내", "2. 복학 신청 안내"처럼 번호로 주제가 나뉘어 있어서,
              번호에서 자르면 한 청크에 한 주제만 담긴다. (A는 두 주제가 한 청크에 섞인다)
      이유 2. 번호가 없는 문서는 덩어리가 하나뿐이라 A와 똑같이 동작한다. (A보다 나빠질 일이 없다)
      이유 3. "2026. 7. 27." 같은 날짜 줄은 is_heading()이 걸러서 잘못 끊기지 않는다.
      (이 내용은 weekly/W1.md에도 옮겨 적을 것)

    하는 일:
      1. 큰 번호 제목 줄이 나올 때마다 덩어리(section)를 새로 시작하기
      2. 덩어리마다 pack_lines()로 max_chars 이하가 되게 자르기
    """
    # 1. 큰 번호 제목 줄이 나올 때마다 덩어리(section)를 새로 시작
    sections = []
    current = []  # 지금 모으고 있는 덩어리의 줄들

    for line in text.split("\n"):
        if is_heading(line) and len(current) > 0:
            sections.append(current)   # 지금까지 모은 덩어리를 저장하고
            current = []               # 새 덩어리 시작
        current.append(line)

    if len(current) > 0:
        sections.append(current)       # 마지막 덩어리도 저장

    # 2. 덩어리마다 A 방식(pack_lines)으로 자르기
    #    max_chars 이하인 덩어리는 그대로 청크 1개, 긴 덩어리만 여러 개로 나뉜다.
    chunks = []
    for section in sections:
        for chunk in pack_lines(section, max_chars):
            chunks.append(chunk)
    return chunks


def save_jsonl(records, path):
    """records의 dict를 한 줄에 하나씩 JSON으로 저장한다.

    하는 일:
      1. open(path, "w", encoding="utf-8")로 파일 열기
         - 이유: 윈도우 기본 인코딩(cp949)으로 열면 본문의 •, ∙, ▸ 같은 기호를
           저장하지 못해 에러가 난다.
      2. 각 record를 json.dumps(record, ensure_ascii=False) + "\\n"으로 한 줄씩 쓰기
         - 이유: ensure_ascii=False가 없으면 한글이 \\uXXXX로 저장돼 사람이 읽을 수 없다.
           한 줄에 하나씩 쓰면(JSONL) 나중에 한 줄씩 읽어 처리하기 쉽다.
    """
    # 1. UTF-8로 파일 열기
    with open(path, "w", encoding="utf-8") as f:
        # 2. record를 한 줄에 하나씩 쓰기
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    docs = load_documents(RAW_DIR)
    print(f"문서 {len(docs)}개를 읽었어요.")
    print("--- 첫 문서 앞부분 ---")
    print(docs[0]["title"])
    print(clean(docs[0]["text"])[:300])
    print("---")

    records = []
    for doc in docs:
        for i, chunk in enumerate(split_chunks(clean(doc["text"]))):
            # 생각해 볼 것: chunk 앞에 doc["title"]을 붙이면 검색이 나아질까?
            records.append({
                "id": f"{doc['doc_id']}-{i:03d}",
                "source": doc["source"],
                "text": chunk,
            })

    lengths = [len(r["text"]) for r in records]
    print(f"청크 {len(records)}개, 평균 {sum(lengths) / len(lengths):.0f}자, "
          f"최소 {min(lengths)}자, 최대 {max(lengths)}자")

    save_jsonl(records, OUT_PATH)
    print(f"{OUT_PATH}에 저장했어요.")


if __name__ == "__main__":
    main()

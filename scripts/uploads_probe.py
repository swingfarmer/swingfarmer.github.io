#!/usr/bin/env python3
"""(143 임시 — 끝나면 git rm) ~/uploads 옛 이미지가 게시판·메모·댓글 글에 쓰였는지 개수만 본다.
읽기만 함. 원래 파일 이름(original_name)·글 제목·내용은 출력하지 않음.

실행: . ~/.env_secrets && cd ~ && python3 ~/swingfarmer.github.io/scripts/uploads_probe.py
(api_server.py 홈 복사본의 DB 연결을 빌려 씀)
"""
import os, sys, glob, hashlib
sys.path.insert(0, os.path.expanduser('~'))
import api_server as A

UP = os.path.expanduser('~/uploads')
files = sorted(glob.glob(os.path.join(UP, '*', '*', '*')))
conn = A.get_conn(); cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM attachments"); print('attachments 행 수:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM posts"); print('posts 글 수:', cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM notes"); print('notes 글 수:', cur.fetchone()[0])
print()
print('파일 / 같은 내용 묶음 / attachments 기록 / 쓰인 글 수(posts·notes·comments)')
seen = {}
for f in files:
    rel = os.path.relpath(f, UP)
    name = os.path.basename(f)
    h = hashlib.md5(open(f, 'rb').read()).hexdigest()[:6]
    grp = seen.setdefault(h, chr(ord('A') + len(seen)))
    cur.execute("SELECT COUNT(*) FROM attachments WHERE stored_path=:p", {'p': rel})
    att = cur.fetchone()[0]
    used = []
    for t in ('posts', 'notes', 'comments'):
        cur.execute(f"SELECT COUNT(*) FROM {t} WHERE INSTR(content, :n) > 0", {'n': name})
        used.append(cur.fetchone()[0])
    print(f'  {rel:32s} 묶음 {grp}  기록 {att}  글 {used[0]}·{used[1]}·{used[2]}')
cur.close(); conn.close()
print('\n같은 묶음 글자 = 내용이 똑같은 파일(중복 업로드)')

"""In-memory Mini Git. Run with Python 3.10 or later."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import shlex
from typing import Callable, TypeVar

T = TypeVar('T')


def merge_sort(items: list[T], key: Callable) -> list[T]:
    """Stable merge sort: O(n log n) time and O(n) auxiliary space."""
    result = list(items)
    width = 1
    while width < len(result):
        merged = []
        for start in range(0, len(result), width * 2):
            left = result[start:start + width]
            right = result[start + width:start + 2 * width]
            i = j = 0
            while i < len(left) and j < len(right):
                if key(left[i]) <= key(right[j]):
                    merged.append(left[i])
                    i += 1
                else:
                    merged.append(right[j])
                    j += 1
            merged.extend(left[i:])
            merged.extend(right[j:])
        result = merged
        width *= 2
    return result


@dataclass(frozen=True)
class Commit:
    """Immutable graph node; parents point only to existing commits."""
    hash: str
    message: str
    author: str
    timestamp: datetime
    parents: tuple[str, ...]


class InvertedIndex:
    """Posting lists preserve insertion order and avoid full-store searches."""
    def __init__(self):
        self.keywords: dict[str, list[str]] = {}
        self.authors: dict[str, list[str]] = {}

    def add(self, commit: Commit) -> None:
        for token in dict.fromkeys(commit.message.lower().split()):
            self.keywords.setdefault(token, []).append(commit.hash)
        self.authors.setdefault(commit.author, []).append(commit.hash)

    def search(self, query: str, author: bool = False) -> list[str]:
        if author:
            return list(self.authors.get(query, []))
        tokens = list(dict.fromkeys(query.lower().split()))
        if not tokens:
            return []
        postings = [self.keywords.get(token, []) for token in tokens]
        # Multi-word queries mean AND across normalized, exact tokens.
        smallest = min(postings, key=len)
        memberships = [set(posting) for posting in postings]
        return [h for h in smallest if all(h in group for group in memberships)]


def topological_order(commits: dict[str, Commit]) -> list[str]:
    """Kahn traversal over all branches, always emitting parents first."""
    degrees = {h: len(c.parents) for h, c in commits.items()}
    children = {h: [] for h in commits}
    for h, commit in commits.items():
        for parent in commit.parents:
            children[parent].append(h)
    queue = deque(h for h in commits if degrees[h] == 0)
    result = []
    while queue:
        h = queue.popleft()
        result.append(h)
        for child in children[h]:
            degrees[child] -= 1
            if degrees[child] == 0:
                queue.append(child)
    if len(result) != len(commits):
        raise ValueError('Invalid commit graph')
    return result


def shortest_path(adjacency: dict[str, set[str]], start: str, end: str) -> list[str]:
    """BFS with lexical neighbors selects the lexically first shortest path."""
    queue = deque([start])
    previous: dict[str, str | None] = {start: None}
    while queue:
        current = queue.popleft()
        if current == end:
            path = []
            while current is not None:
                path.append(current)
                current = previous[current]
            return path[::-1]
        for neighbor in merge_sort(list(adjacency[current]), key=lambda h: h):
            if neighbor not in previous:
                previous[neighbor] = current
                queue.append(neighbor)
    return []


def ancestors(commits: dict[str, Commit], start: str) -> list[str]:
    """Iterative DFS finds every ancestor once, without recursion limits."""
    visited = set()
    stack = list(commits[start].parents)
    result = []
    while stack:
        h = stack.pop()
        if h not in visited:
            visited.add(h)
            result.append(h)
            stack.extend(commits[h].parents)
    return result


class MiniGit:
    """Repository state and strict CLI command dispatch."""
    def __init__(self):
        self.user: str | None = None
        self.branch = 'main'
        self.branches: dict[str, str | None] = {}
        self.commits: dict[str, Commit] = {}
        self.adjacency: dict[str, set[str]] = {}
        self.index = InvertedIndex()
        self.counter = 0

    def require_commit(self, h: str) -> None:
        if h not in self.commits:
            raise ValueError(f'Unknown commit: {h}')

    def format_commits(self, hashes: list[str]) -> str:
        if not hashes:
            return 'No commits'
        lines = []
        for h in hashes:
            c = self.commits[h]
            labels = [name for name, head in self.branches.items() if head == h]
            suffix = f" [{', '.join(labels)}]" if labels else ''
            lines.append(f'commit {h} ({c.author}, {c.timestamp.isoformat()}){suffix}\n  {c.message}')
        return '\n'.join(lines)

    def execute(self, line: str) -> str:
        """Parse a command; errors are printable and do not terminate the REPL."""
        try:
            # 따옴표 안의 공백은 유지하면서 명령어와 인자를 나눕니다.
            # 예: COMMIT "첫 번째 커밋" → [COMMIT, 첫 번째 커밋]
            parts = shlex.split(line)
            if not parts:
                return ''
            command, *args = parts
            # 명령어만 대문자로 바꿔 init, Init, INIT을 동일하게 처리합니다.
            command = command.upper()
            # EXIT / QUIT: 종료를 요청합니다. main()이 Bye!를 받으면 반복을 끝냅니다.
            if command in ('EXIT', 'QUIT'):
                if args:
                    raise ValueError('Invalid args')
                return 'Bye!'
            # HELP: 사용할 수 있는 명령어와 인자 형식을 안내합니다.
            if command == 'HELP':
                if args:
                    raise ValueError('Invalid args')
                return ('INIT <user_name> | BRANCH <name> | SWITCH <name> | COMMIT <message>\n'
                        'LOG [--sort-by=date|author] | PATH <hash1> <hash2>\n'
                        'ANCESTORS <hash> | SEARCH <keyword> | SEARCH --author=<name>\n'
                        'HELP | EXIT | QUIT')
            # 명령어별 허용 인자 개수입니다. LOG는 인자 없이 또는 옵션 1개로 사용합니다.
            arities = {'INIT': (1,), 'BRANCH': (1,), 'SWITCH': (1,),
                       'COMMIT': (1,), 'LOG': (0, 1), 'PATH': (2,),
                       'ANCESTORS': (1,), 'SEARCH': (1,)}
            if command not in arities:
                return f'Unknown command: {command}'
            if len(args) not in arities[command] or any(not a.strip() for a in args):
                raise ValueError('Invalid args')
            # INIT <사용자명>: 저장소를 초기화하고 작성자와 빈 main 브랜치를 설정합니다.
            # 예: INIT Jiyoung / INIT "Jiyoung Lee"
            if command == 'INIT':
                if self.user is not None:
                    raise ValueError('Repository already initialized')
                self.user = args[0]
                self.branches['main'] = None
                return f'Initialized repository.\nCurrent branch: main\nCurrent user: {self.user}'
            # 초기화 전에 커밋·브랜치 등의 명령을 실행하지 못하도록 검사합니다.
            if self.user is None:
                raise ValueError('Repository not initialized')
            # BRANCH <이름>: 현재 커밋을 가리키는 새 브랜치를 만듭니다.
            # 예: BRANCH feature — 생성만 하며 현재 브랜치는 바꾸지 않습니다.
            if command == 'BRANCH':
                if args[0] in self.branches:
                    raise ValueError(f'Branch already exists: {args[0]}')
                self.branches[args[0]] = self.branches[self.branch]
                return f'Created branch: {args[0]}'
            # SWITCH <이름>: 작업할 브랜치를 변경합니다. 예: SWITCH feature
            # 파일을 바꾸는 기능은 없으며 이후 커밋을 연결할 브랜치를 선택합니다.
            if command == 'SWITCH':
                if args[0] not in self.branches:
                    raise ValueError(f'Unknown branch: {args[0]}')
                self.branch = args[0]
                return f'Switched to branch: {self.branch}'
            # COMMIT <메시지>: 현재 브랜치의 HEAD를 부모로 새 커밋을 만듭니다.
            # 예: COMMIT "로그인 기능 추가" — 실제 파일 내용은 저장하지 않습니다.
            if command == 'COMMIT':
                self.counter += 1
                # 증가 카운터를 16자리 이상의 16진수로 표현해 세션 내 중복을 방지합니다.
                h = f'{self.counter:016x}'
                head = self.branches[self.branch]
                parents = (head,) if head is not None else ()
                c = Commit(h, args[0], self.user, datetime.now(timezone.utc), parents)
                self.commits[h] = c
                # PATH가 양방향으로 이동할 수 있도록 부모·자식 연결을 함께 기록합니다.
                self.adjacency[h] = set(parents)
                for parent in parents:
                    self.adjacency[parent].add(h)
                # 현재 브랜치의 HEAD를 이동하고 키워드·작성자 역색인을 갱신합니다.
                self.branches[self.branch] = h
                self.index.add(c)
                return f'[{self.branch} {h}] {c.message}'
            # LOG: 모든 브랜치의 커밋을 부모가 자식보다 먼저 나오게 출력합니다.
            # LOG --sort-by=date: 날짜 오름차순 / --sort-by=author: 작성자 사전순
            # 옵션 정렬에서는 위상 순서 대신 지정한 비교 기준을 우선합니다.
            if command == 'LOG':
                if not args:
                    return self.format_commits(topological_order(self.commits))
                if args[0] not in ('--sort-by=date', '--sort-by=author'):
                    raise ValueError('Invalid args')
                field = 'timestamp' if args[0].endswith('date') else 'author'
                ordered = merge_sort(list(self.commits.values()), key=lambda c: getattr(c, field))
                return self.format_commits([c.hash for c in ordered])
            # PATH <시작 해시> <도착 해시>: 부모 연결을 무방향으로 보고 최단 경로를 찾습니다.
            # BFS를 사용하고, 길이가 같으면 경로 문자열의 사전순이 가장 작은 것을 선택합니다.
            if command == 'PATH':
                for h in args:
                    self.require_commit(h)
                path = shortest_path(self.adjacency, *args)
                return 'Path: ' + '->'.join(path) if path else 'No path'
            # ANCESTORS <해시>: 부모 방향으로 DFS하여 모든 조상을 한 번씩 출력합니다.
            # 조회 대상 자신과 형제 커밋은 조상에 포함하지 않습니다.
            if command == 'ANCESTORS':
                self.require_commit(args[0])
                found = ancestors(self.commits, args[0])
                return self.format_commits(found) if found else 'No ancestors'
            # 위 명령은 모두 결과를 반환했으므로 여기에는 SEARCH만 도달합니다.
            # SEARCH <키워드>: 소문자·공백 분리 토큰으로 검색합니다. 예: SEARCH "로그인"
            # 여러 단어는 AND 검색입니다. 예: SEARCH "로그인 기능"
            # SEARCH --author=<이름>: 작성자가 정확히 일치하는 커밋을 검색합니다.
            # 예: SEARCH --author=Jiyoung / SEARCH --author="Jiyoung Lee"
            query = args[0]
            by_author = query.startswith('--author=')
            if query.startswith('--') and not by_author:
                raise ValueError('Invalid args')
            if by_author:
                query = query[len('--author='):]
                if not query.strip():
                    raise ValueError('Invalid args')
            found = self.index.search(query, author=by_author)
            return f'Found {len(found)} commit(s):\n' + self.format_commits(found)
        except ValueError as error:
            # shlex errors (e.g. unmatched quotes) use the same CLI error format.
            if str(error) in ('No closing quotation', 'No escaped character'):
                return 'Invalid args'
            return str(error)


def main() -> None:
    """Read, execute and print until exit, quit, EOF or keyboard interrupt."""
    # 실행 중인 한 세션의 저장소입니다. 종료하면 이 객체의 기록은 사라집니다.
    repo = MiniGit()
    print('Mini Git — type HELP for commands.')
    while True:
        try:
            # 프롬프트 뒤에 명령어만 입력합니다. pwd·git push는 종료 후 일반 터미널에서 사용합니다.
            line = input('mini-git> ')
        except (EOFError, KeyboardInterrupt):
            print('\nBye!')
            break
        output = repo.execute(line)
        if output:
            print(output)
        if output == 'Invalid args':
            print('입력 형식을 확인하세요. 예: INIT Jiyoung / COMMIT "첫 번째 커밋"')
            print(f'실제 입력: {line!r}')
        if output == 'Unknown command: PWD':
            print('pwd는 터미널 명령입니다. QUIT으로 Mini Git을 종료한 뒤 입력하세요.')
        if output == 'Bye!':
            break


if __name__ == '__main__':
    main()

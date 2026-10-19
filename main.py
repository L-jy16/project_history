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
            parts = shlex.split(line)
            if not parts:
                return ''
            command, *args = parts
            command = command.upper()
            if command in ('EXIT', 'QUIT'):
                if args:
                    raise ValueError('Invalid args')
                return 'Bye!'
            if command == 'HELP':
                if args:
                    raise ValueError('Invalid args')
                return ('INIT <user_name> | BRANCH <name> | SWITCH <name> | COMMIT <message>\n'
                        'LOG [--sort-by=date|author] | PATH <hash1> <hash2>\n'
                        'ANCESTORS <hash> | SEARCH <keyword> | SEARCH --author=<name>\n'
                        'HELP | EXIT | QUIT')
            arities = {'INIT': (1,), 'BRANCH': (1,), 'SWITCH': (1,),
                       'COMMIT': (1,), 'LOG': (0, 1), 'PATH': (2,),
                       'ANCESTORS': (1,), 'SEARCH': (1,)}
            if command not in arities:
                return f'Unknown command: {command}'
            if len(args) not in arities[command] or any(not a.strip() for a in args):
                raise ValueError('Invalid args')
            if command == 'INIT':
                if self.user is not None:
                    raise ValueError('Repository already initialized')
                self.user = args[0]
                self.branches['main'] = None
                return f'Initialized repository.\nCurrent branch: main\nCurrent user: {self.user}'
            if self.user is None:
                raise ValueError('Repository not initialized')
            if command == 'BRANCH':
                if args[0] in self.branches:
                    raise ValueError(f'Branch already exists: {args[0]}')
                self.branches[args[0]] = self.branches[self.branch]
                return f'Created branch: {args[0]}'
            if command == 'SWITCH':
                if args[0] not in self.branches:
                    raise ValueError(f'Unknown branch: {args[0]}')
                self.branch = args[0]
                return f'Switched to branch: {self.branch}'
            if command == 'COMMIT':
                self.counter += 1
                h = f'{self.counter:016x}'
                head = self.branches[self.branch]
                parents = (head,) if head is not None else ()
                c = Commit(h, args[0], self.user, datetime.now(timezone.utc), parents)
                self.commits[h] = c
                self.adjacency[h] = set(parents)
                for parent in parents:
                    self.adjacency[parent].add(h)
                self.branches[self.branch] = h
                self.index.add(c)
                return f'[{self.branch} {h}] {c.message}'
            if command == 'LOG':
                if not args:
                    return self.format_commits(topological_order(self.commits))
                if args[0] not in ('--sort-by=date', '--sort-by=author'):
                    raise ValueError('Invalid args')
                field = 'timestamp' if args[0].endswith('date') else 'author'
                ordered = merge_sort(list(self.commits.values()), key=lambda c: getattr(c, field))
                return self.format_commits([c.hash for c in ordered])
            if command == 'PATH':
                for h in args:
                    self.require_commit(h)
                path = shortest_path(self.adjacency, *args)
                return 'Path: ' + '->'.join(path) if path else 'No path'
            if command == 'ANCESTORS':
                self.require_commit(args[0])
                found = ancestors(self.commits, args[0])
                return self.format_commits(found) if found else 'No ancestors'
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
    repo = MiniGit()
    print('Mini Git — type HELP for commands.')
    while True:
        try:
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

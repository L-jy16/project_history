"""Functional and algorithm checks using only the standard library."""
import unittest
from datetime import datetime, timezone
from main import MiniGit, Commit, InvertedIndex, merge_sort, shortest_path, ancestors, topological_order


class MiniGitTests(unittest.TestCase):
    def test_branch_graph_and_search(self):
        r = MiniGit()
        self.assertIn('not initialized', r.execute('LOG'))
        r.execute('init "Alice Kim"')
        r.execute('commit "Initial commit"')
        root = r.branches['main']
        r.execute('branch feature')
        r.execute('switch feature')
        r.execute('commit "Add login LOGIN"')
        feature = r.branches['feature']
        r.execute('switch main')
        r.execute('commit "Add payment"')
        main = r.branches['main']
        self.assertEqual(r.commits[main].parents, (root,))
        self.assertEqual(r.index.search('LOGIN'), [feature])
        self.assertEqual(r.index.search('add login'), [feature])
        self.assertEqual(len(r.index.search('Alice Kim', author=True)), 3)
        self.assertIn(f'{feature}->{root}->{main}', r.execute(f'path {feature} {main}'))
        order = topological_order(r.commits)
        self.assertLess(order.index(root), order.index(feature))
        self.assertLess(order.index(root), order.index(main))
        self.assertEqual(ancestors(r.commits, feature), [root])
        self.assertIn('Found 3', r.execute('search --author="Alice Kim"'))
        self.assertIn('commit', r.execute('log --sort-by=date'))
        self.assertIn('commit', r.execute('log --sort-by=author'))
        self.assertIn('already initialized', r.execute('init Bob'))
        self.assertEqual(r.user, 'Alice Kim')

    def test_disconnected_roots(self):
        r = MiniGit()
        r.execute('init Alice')
        r.execute('branch orphan')
        r.execute('commit one')
        a = r.branches['main']
        r.execute('switch orphan')
        r.execute('commit two')
        b = r.branches['orphan']
        self.assertEqual(r.execute(f'path {a} {b}'), 'No path')
        self.assertEqual(r.execute(f'path {a} {a}'), f'Path: {a}')
        self.assertEqual(r.execute(f'ancestors {a}'), 'No ancestors')

    def test_error_handling(self):
        r = MiniGit()
        for command in ('init', 'init "', 'init ""', 'quit extra', 'HELP x'):
            self.assertEqual(r.execute(command), 'Invalid args')
        r.execute('init Alice')
        self.assertEqual(r.execute('switch missing'), 'Unknown branch: missing')
        self.assertEqual(r.execute('path x y'), 'Unknown commit: x')
        for command in ('log --sort-by=no', 'search --author=', 'commit a b'):
            self.assertEqual(r.execute(command), 'Invalid args')
        self.assertEqual(r.execute('quit'), 'Bye!')

    def test_sort_stability_and_author_index(self):
        items = [(2, 'a'), (1, 'b'), (2, 'c'), (1, 'd')]
        self.assertEqual(merge_sort(items, key=lambda x: x[0]),
                         [(1, 'b'), (1, 'd'), (2, 'a'), (2, 'c')])
        self.assertEqual(merge_sort([], key=lambda x: x), [])
        index = InvertedIndex()
        for h, author in [('a', 'Zoe'), ('b', 'Alice')]:
            index.add(Commit(h, 'hello hello', author, datetime.now(timezone.utc), ()))
        self.assertEqual(index.search('hello'), ['a', 'b'])
        self.assertEqual(index.search('Alice', author=True), ['b'])

    def test_lexical_shortest_path_and_diamond_ancestors(self):
        graph = {'s': {'b', 'a'}, 'a': {'s', 'z'}, 'b': {'s', 'z'}, 'z': {'a', 'b'}}
        self.assertEqual(shortest_path(graph, 's', 'z'), ['s', 'a', 'z'])
        now = datetime.now(timezone.utc)
        commits = {h: Commit(h, h, 'A', now, parents) for h, parents in
                   [('root', ()), ('left', ('root',)), ('right', ('root',)),
                    ('tip', ('left', 'right'))]}
        self.assertEqual(set(ancestors(commits, 'tip')), {'root', 'left', 'right'})
        order = topological_order(commits)
        for h, c in commits.items():
            for p in c.parents:
                self.assertLess(order.index(p), order.index(h))

    def test_unique_hashes(self):
        r = MiniGit()
        r.execute('init A')
        for _ in range(1000):
            r.execute('commit repeated')
        self.assertEqual(len(r.commits), 1000)
        self.assertEqual(len(ancestors(r.commits, r.branches['main'])), 999)


if __name__ == '__main__':
    unittest.main()

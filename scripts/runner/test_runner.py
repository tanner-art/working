import unittest
from runner import select
class QueueTests(unittest.TestCase):
    def issue(self,body=None):
        return {'author':{'login':'owner'},'labels':[{'name':'agent:codex-a'}], 'body':body or '{"task":"TASK-015","paths":["docs/example.md"],"instructions":"Write a note"}'}
    def test_valid(self): self.assertEqual(select(self.issue(),['owner'])[0],'codex-a')
    def test_untrusted_author(self):
        with self.assertRaises(ValueError): select(self.issue(),['someone'])
    def test_traversal(self):
        with self.assertRaises(ValueError): select(self.issue('{"task":"TASK-015","paths":["../secret"],"instructions":"x"}'),['owner'])
    def test_two_agents(self):
        i=self.issue();i['labels'].append({'name':'agent:claude'})
        with self.assertRaises(ValueError): select(i,['owner'])
    def test_completed_not_repeated(self):
        i=self.issue();i['labels'].append({'name':'runner:review'})
        with self.assertRaises(ValueError): select(i,['owner'])
if __name__=='__main__': unittest.main()

from extendedcaos import extendedcaos_to_caos
import unittest

class TestExtendedCAOS(unittest.TestCase):
    def test_idempotent(self):
        s = "  * hello\nnew: comp 3 1 21051 \"elevines\" 13 4 2000"
        self.assertEqual(s, extendedcaos_to_caos(s))
    
    def test_moves_comments_to_own_line(self):
        input = "    _cd_ ejct* open cd tray\nbang"
        desired_output = "    * open cd tray\n    _cd_ ejct\nbang"
        self.assertEqual(desired_output, extendedcaos_to_caos(input))
        
        input = "    _cd_ ejct  * open cd tray\nbang"
        desired_output = "    * open cd tray\n    _cd_ ejct\nbang"
        self.assertEqual(desired_output, extendedcaos_to_caos(input))
        
        input = "    _cd_ ejct  * open cd tray\n* another"
        desired_output = "    * open cd tray\n    _cd_ ejct\n* another"
        self.assertEqual(desired_output, extendedcaos_to_caos(input))
        
        input = "    _cd_ ejct  * open cd tray\n * another"
        desired_output = "    * open cd tray\n    _cd_ ejct\n * another"
        self.assertEqual(desired_output, extendedcaos_to_caos(input))
        
        input = "    * open cd tray"
        desired_output = "    * open cd tray"
        self.assertEqual(desired_output, extendedcaos_to_caos(input))
    
    def test_parses_comment_at_eoi(self):
        s = "* comment at eoi"
        self.assertEqual(s, extendedcaos_to_caos(s))
        s = "* comment at eoi\n"
        self.assertEqual(s, extendedcaos_to_caos(s))
    
if __name__ == '__main__':
    unittest.main()
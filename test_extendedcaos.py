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
    
    def test_named_variables(self):
        input = """
            sets $hello 5
            setv $hello "world"
            setv va01 8
            setv $another "world"
            
            scrp 1 2 3 1000
                setv va00 0
                setv va01 1
                setv va03 3
                setv $avariable 2
            endm
            
            scrp 1 2 3 1001
                setv va00 0
                setv $hello 1
                setv va02 2
                setv $another 3
                setv $avariable 4
            endm
            
            scrp 1 2 3 1002
                setv $start 5
                gsub subroutine
                subr subroutine
                    setv va00 6
                retn
            endm
            
            rscr
            enum 1 2 3
                setv $posy posy
            next
        """
        desired_output = """
            sets va00 5
            setv va00 "world"
            setv va01 8
            setv va02 "world"
            
            scrp 1 2 3 1000
                setv va00 0
                setv va01 1
                setv va03 3
                setv va02 2
            endm
            
            scrp 1 2 3 1001
                setv va00 0
                setv va01 1
                setv va02 2
                setv va03 3
                setv va04 4
            endm
            
            scrp 1 2 3 1002
                setv va01 5
                gsub subroutine
                subr subroutine
                    setv va00 6
                retn
            endm
            
            rscr
            enum 1 2 3
                setv va00 posy
            next
        """
        self.assertEqual(desired_output, extendedcaos_to_caos(input))
    
    
if __name__ == '__main__':
    unittest.main()
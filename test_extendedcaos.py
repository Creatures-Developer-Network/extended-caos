from extendedcaos import extendedcaos_to_caos
import unittest


class TestExtendedCAOS(unittest.TestCase):
    maxDiff = 999999999

    def test_idempotent(self):
        s = '  * hello\nnew: comp 3 1 21051 "elevines" 13 4 2000'
        self.assertMultiLineEqual(s, extendedcaos_to_caos(s))

    def test_moves_comments_to_own_line(self):
        input = "    stop* open cd tray\nstop"
        desired_output = "    * open cd tray\n    stop\nstop"
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = "    stop  * open cd tray\nstop"
        desired_output = "    * open cd tray\n    stop\nstop"
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = "    stop  * open cd tray\n* another"
        desired_output = "    * open cd tray\n    stop\n* another"
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = "    stop  * open cd tray\n * another"
        desired_output = "    * open cd tray\n    stop\n * another"
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = "    * open cd tray"
        desired_output = "    * open cd tray"
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_parses_comment_at_eoi(self):
        s = "* comment at eoi"
        self.assertMultiLineEqual(s, extendedcaos_to_caos(s))
        s = "* comment at eoi\n"
        self.assertMultiLineEqual(s, extendedcaos_to_caos(s))

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
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_explicit_targ(self):
        input = """
            from.mvsf 5 6
            ownr.mvsf 6 5
            dbg: outv from.angl 0 0
        """
        desired_output = """
            seta va00 targ
            targ from
            mvsf 5 6
            targ va00
            seta va00 targ
            targ ownr
            mvsf 6 5
            targ va00
            seta va00 targ
            targ from
            setv va01 angl 0 0
            targ va00
            dbg: outv va01
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = """
            dbg: outv angl va00.posx va00.posy
        """
        desired_output = """
            seta va01 targ
            targ va00
            setv va02 posx
            targ va01
            seta va01 targ
            targ va00
            setv va03 posy
            targ va01
            dbg: outv angl va02 va03
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = """
            dbg: outv from.angl va00.posx va00.posy
        """
        desired_output = """
            seta va01 targ
            targ va00
            setv va02 posx
            targ va01
            seta va01 targ
            targ va00
            setv va03 posy
            targ va01
            seta va01 targ
            targ from
            setv va04 angl va02 va03
            targ va01
            dbg: outv va04
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = """
            doif $targetring.movs ne 0
        """
        desired_output = """
            seta va00 targ
            targ va01
            setv va02 movs
            targ va00
            doif va02 ne 0
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

        input = """
            dbg: outv $targetring.movs
            dbg: outs $targetring.gall
            seta va99 $targetring.carr
        """
        desired_output = """
            seta va00 targ
            targ va01
            setv va02 movs
            targ va00
            dbg: outv va02
            seta va00 targ
            targ va01
            sets va03 gall
            targ va00
            dbg: outs va03
            seta va00 targ
            targ va01
            seta va04 carr
            targ va00
            seta va99 va04
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_explicit_targ_in_doif(self):
        input = """
            doif movs <> 0
                dbg: outv 0
                doif 0 < 1
                endi
            elif posy > ownr.posy
                dbg: outv 1
            else
                dbg: outv 2
            endi
        """
        desired_output = """
            seta va00 targ
            targ ownr
            setv va01 posy
            targ va00
            doif movs <> 0
                dbg: outv 0
                doif 0 < 1
                endi
            elif posy > va01
                dbg: outv 1
            else
                dbg: outv 2
            endi
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_object_variables(self):
        input = """
            agent_variable $bioenergy ov63
            subv targ.$bioenergy 1
            subv ownr.$bioenergy 2
            subv from.$bioenergy 3
        """
        desired_output = """
            
            subv ov63 1
            subv mv63 2
            subv avar from 63 3
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))


if __name__ == "__main__":
    unittest.main()

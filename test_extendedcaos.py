from extendedcaos import *
from caoslexer import *
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
            targ ownr
            mvsf 6 5
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
            setv va03 posy
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

    def test_explicit_targ_other_commands(self):
        input = """
            $targetring.tick tick
            dbg: outv $targetring.tmvt posx posy
        """
        desired_output = """
            setv va00 tick
            seta va01 targ
            targ va02
            tick va00
            targ va01
            setv va03 posx
            setv va04 posy
            seta va01 targ
            targ va02
            setv va05 tmvt va03 va04
            targ va01
            dbg: outv va05
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_remove_extraneous_targ_saving(self):
        input = """
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
        desired_output = """
            seta va01 targ
            targ va00
            setv va02 posx
            setv va03 posy
            targ from
            setv va04 angl va02 va03
            targ va01
            dbg: outv va04
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_remove_double_targ(self):
        input = """
            targ ownr
            targ va00
            targ va01
            setv va02 posx
            targ va01
        """
        desired_output = """
            targ va01
            setv va02 posx
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

    def test_get_indentation_at(self):
        self.assertEqual(get_indentation_at(lexcaos("  "), 0), "  ")
        self.assertEqual(get_indentation_at(lexcaos("  bang"), 1), "  ")
        self.assertEqual(get_indentation_at(lexcaos("  \n    bang"), 2,), "    ")
        self.assertEqual(get_indentation_at(lexcaos("  \n    bang"), 3), "    ")
        self.assertEqual(
            get_indentation_at(
                [
                    (TOK_WHITESPACE, ""),
                    (TOK_WHITESPACE, "  "),
                    (TOK_WHITESPACE, "  "),
                    (TOK_WORD, "bang"),
                    (TOK_EOI, None),
                ],
                3,
            ),
            "    ",
        )

    def test_strip_indent(self):
        self.assertMultiLineEqual(
            tokens_to_string(strip_indent(lexcaos("  bang\n    bang\nbang"))),
            "bang\n  bang\nbang",
        )

    def test_add_indent(self):
        self.assertMultiLineEqual(
            tokens_to_string(add_indent(lexcaos("bang\n  bang"), "  ")),
            "  bang\n    bang",
        )

    def test_macros_toplevel(self):
        input = """
        macro CreateMyAgent sprite_name
            sets $sprite_name lowa $sprite_name
            new: simp 1 2 1001 $sprite_name 13 4 2000
        endmacro
        sets $sprite_name "MY SPRITE"
        * macro with variable
        CreateMyAgent $sprite_name
        * macro with literal
        CreateMyAgent "my sprite"
        * macro with command of an unknown result type
        CreateMyAgent from
        * make sure original variable is untouched
        dbg: outs $sprite_name
        """
        desired_output = """
        sets va00 "MY SPRITE"
        * macro with variable
        doif type va00 = 0 or type va00 = 1 setv va01 va00 elif type va00 = 2 sets va01 va00 else seta va01 va00 endi
        sets va01 lowa va01
        new: simp 1 2 1001 va01 13 4 2000
        * macro with literal
        sets va01 "my sprite"
        sets va01 lowa va01
        new: simp 1 2 1001 va01 13 4 2000
        * macro with command of an unknown result type
        doif type from = 0 or type from = 1 setv va01 from elif type from = 2 sets va01 from else seta va01 from endi
        sets va01 lowa va01
        new: simp 1 2 1001 va01 13 4 2000
        * make sure original variable is untouched
        dbg: outs va00
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_macros_toplevel2(self):
        # This had gotten broken by some issues around lower-casing targ names for explicit targs
        input = """
        macro CreateElevine parent
        	dbg: outv $parent.clac
        endmacro
        CreateElevine null
        """
        desired_output = """
        seta va00 null
        seta va01 targ
        targ va00
        setv va02 clac
        targ va01
        dbg: outv va02
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_macros_toplevel3(self):
        # This was broken by including an erroneous TOK_EOI in the macro body and pasting it into the main script
        input = """
        macro CreateElevine parent
        	dbg: outv $parent.clac
        endmacro
        CreateElevine null
        
        CreateElevine null
        """
        desired_output = """
        seta va00 null
        seta va01 targ
        targ va00
        setv va02 clac
        targ va01
        dbg: outv va02
        
        seta va00 null
        seta va01 targ
        targ va00
        setv va03 clac
        targ va01
        dbg: outv va03
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_macros_exception_on_bad_argnames(self):
        with self.assertRaises(Exception):
            extendedcaos_to_caos("macro MyMacro $arg1\nendmacro")

    def test_constants(self):
        input = """
        constant :my_classifier 3 21 4000
        constant :my_clac_script_number 1000
        new: simp :my_classifier "sprite_name" 1 1 1000
        dbg: outv :my_clac_script_number
        """
        desired_output = """
        new: simp 3 21 4000 "sprite_name" 1 1 1000
        dbg: outv 1000
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_agentvariable_on_variable(self):
        input = """
        agent_variable $unique_pose ov96
        dbg: outs $parent.$unique_pose
        """
        desired_output = """
        dbg: outs avar va00 96
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_short_circuit_doifs(self):
        input = """
        doif $parent = null or posy > $parent.posy and 1 eq 2
            dbg: outv "true"
        else
            dbg: outv "false"
        endi
        """
        desired_output = """
setv va00 0
            doif va01 = null
              setv va00 1
            endi
            doif va00 = 0
              seta va02 targ
              targ va01
              setv va03 posy
              targ va02
              doif posy > va03
                setv va00 1
              endi
            endi
            doif va00 = 1
              doif 1 eq 2
              else
                setv va00 0
              endi
            endi
            doif va00 = 1
                        dbg: outv "true"
        else
            dbg: outv "false"
        endi
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))

    def test_short_circuit_within_macros(self):
        input = """
        macro MyMacro
            doif $parent = null or posy > $parent.posy
                dbg: outs "true"
            endi
        endmacro
        MyMacro
        """
        desired_output = """
                setv va00 0
                        doif va01 = null
                          setv va00 1
                        endi
                        doif va00 = 0
                          seta va02 targ
                          targ va01
                          setv va03 posy
                          targ va02
                          doif posy > va03
                            setv va00 1
                          endi
                        endi
                        doif va00 = 1
                                        dbg: outs "true"
                    endi
        """
        self.assertMultiLineEqual(desired_output, extendedcaos_to_caos(input))


if __name__ == "__main__":
    unittest.main()

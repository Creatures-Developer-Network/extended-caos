# Extended CAOS

A higher-level language that compiles down to [CAOS](https://creatures.wiki/CAOS).

e.g.

```
agent_variable $unique_id ov99
constant :elevine_classifier 3 1 21051
constant :script_activate1 1
constant :noun_elevator 26
constant :verb_reset -1
constant :stimulus_disappoint 0

macro CreateElevine
    new: comp :elevine_classifier "elevines" 13 4 2000
    bhvr 3
	tick 30
	attr 198
    setv targ.$unique_id rand 0 12
endmacro

macro TeleportCreature targetring
    doif from = null or from.fmly <> 4
        stop
    endi
    *So $targetring should be the ideal ring to tele to now
    *assuming there is one.
    *if there's NOT, stop this whole thing now!
    doif $targetring eq null
        *put a bug in it's ear-- stop pushing this!
        urge writ from :noun_elevator -2 :verb_reset 2
        stim writ from :stimulus_disappoint 1
        sndc "buzz"
        stop
    endi
    * and so on...
endmacro

*Create initial elevine
CreateElevine
mvsf 6110 9200

*Push -- Want to go up
scrp :elevine_classifier :script_activate1
    *first off, is it actually possible to go up?
    seta $targetring null
    enum :elevine_classifier
        doif ownr.$unique_id = targ.$unique_id and posy < ownr.posy
            *herein lies the tricky part-- you want it to be lower than the ring
            *being pushed, but higher than the rest.
            doif $targetring = null or posy > $targetring.posy
                seta $targetring targ
            endi
        endi
    next
    TeleportCreature $targetring
endi
```

is transformed into 

```
*Create initial elevine
new: comp 3 1 21051 "elevines" 13 4 2000
bhvr 3
tick 30
attr 198
setv ov99 rand 0 12
mvsf 6110 9200

*Push -- Want to go up
scrp 3 1 21051 1
    *first off, is it actually possible to go up?
    seta va00 null
    enum 3 1 21051
        setv va01 0
        doif mv99 = ov99
            setv va01 1
        endi
        doif va01 = 1
            seta va02 targ
            targ ownr
            setv va03 posy
            targ va02
            doif posy < va03
            else
                setv va01 0
            endi
        endi
        doif va01 = 1
            *herein lies the tricky part-- you want it to be lower than the ring
            *being pushed, but higher than the rest.
            setv va04 0
            doif va00 = null
                setv va04 1
            endi
            doif va04 = 0
                seta va02 targ
                targ va00
                setv va05 posy
                targ va02
                doif posy > va05
                    setv va04 1
                endi
            endi
            doif va04 = 1
                seta va00 targ
            endi
        endi
    next
    doif type va00 = 0 or type va00 = 1
        setv va06 va00
    elif type va00 = 2
        sets va06 va00
    else
        seta va06 va00
    endi
    setv va07 0
    doif from = null
        setv va07 1
    endi
    doif va07 = 0
        seta va02 targ
        targ from
        setv va08 fmly
        targ va02
        doif va08 <> 4
            setv va07 1
        endi
    endi
    doif va07 = 1
        stop
    endi
    *So $targetring should be the ideal ring to tele to now
    *assuming there is one.
    *if there's NOT, stop this whole thing now!
    doif va06 eq null
        *put a bug in it's ear-- stop pushing this!
        urge writ from 26 -2 -1 2
        stim writ from 0 1
        sndc "buzz"
        stop
    endi
endi
```
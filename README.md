# Extended CAOS

A higher-level language that compiles down to [CAOS](https://creatures.wiki/CAOS).

e.g.

```
agent_variable $unique_id ov99

new: comp 3 1 21051 "elevines" 13 4 2000
setv targ.$unique_id rand 0 12

scrp 3 1 21051 1
  seta $targetring null
  enum 3 1 21051
    doif ownr.$unique_id = targ.$unique_id and posy < ownr.posy
      doif $targetring = null
        seta $targetring targ
      elif posy > $targetring.posy
        seta $targetring targ
      endi
    endi
  endi
endi
```

is transformed into 

```
new: comp 3 1 21051 "elevines" 13 4 2000
setv ov99 rand 0 12

scrp 3 1 21051 1
  seta va00 null
  enum 3 1 21051
    seta va01 targ
    targ ownr
    setv va02 posy
    targ va01
    doif mv99 = ov99 and posy < va02
      doif va00 = null
        seta va00 targ
      seta va01 targ
      targ va00
      setv va03 posy
      targ va01
      elif posy > va03
        seta va00 targ
      endi
    endi
  endi
endi
```
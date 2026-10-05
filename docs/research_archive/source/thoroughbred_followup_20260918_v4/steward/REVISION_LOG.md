# Extraction revision log

The first generated audit sample found two attribution failures. A horse that collided with a separately described late starter was incorrectly marked `delayed_start`, and a horse named as an antecedent/source was incorrectly marked `wide` when an anaphoric “동 말” referred to another horse. The final rules require tighter direct predicates, reject the “늦은 [other horse]” construction, and bound wide-path text before another horse token or clause boundary.

Kickback attribution was also narrowed after the first sample showed that a horse named in “X로부터 모래를 맞자” can be the source of kickback rather than the affected horse. The final extractor accepts direct horse predicates only. These changes reduce recall and are preserved here rather than hidden.

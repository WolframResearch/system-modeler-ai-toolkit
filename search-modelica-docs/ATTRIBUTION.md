# Attribution and licensing of bundled documentation

This skill bundles three prebuilt documentation corpora under
`docsearch/data/` (`spec.json`, `docs.json`, and `msl.json`). Their provenance
and licensing differ, so they are described separately below.

## Modelica Language Specification (`spec.json`)

- **Title:** Modelica Language Specification, version 3.6
- **Author / publisher:** Modelica Association and contributors
- **Source:** <https://specification.modelica.org/maint/3.6/>
- **Copyright:** © 1998–2023 Modelica Association and contributors
- **License:** Creative Commons Attribution-ShareAlike 4.0 International
  (CC BY-SA 4.0) — <https://creativecommons.org/licenses/by-sa/4.0/>

`spec.json` contains excerpts of the Modelica Language Specification.
**Changes were made:** the specification's HTML was extracted into plain-text
passages, split into ~542 retrieval chunks, each keyed by its source URL, for
offline BM25 search. No normative content was altered; chunking and formatting
for indexing are the only modifications.

**ShareAlike notice.** Because this material is licensed under CC BY-SA 4.0, the
bundled excerpts in `spec.json` (and any adaptation of them) remain licensed
under CC BY-SA 4.0 and must be redistributed under the same license with this
attribution preserved. Whatever license the wider repository adopts, this
constraint applies to the Modelica Language Specification content specifically.

"Modelica" is a registered trademark of the Modelica Association.

## Wolfram System Modeler documentation (`docs.json`)

- **Title:** Wolfram System Modeler documentation (tutorials, user guide, and
  release notes), version 15.0
- **Author / publisher:** Wolfram Research, Inc.
- **Source:** <https://reference.wolfram.com/system-modeler/>
- **Copyright:** © Wolfram Research, Inc.

`docs.json` contains excerpts of the Wolfram System Modeler product
documentation. This is Wolfram's own documentation, included and distributed
here by Wolfram Research as the developer of the product. **Changes were
made:** the documentation was split into plain-text retrieval chunks, each
keyed by its source URL, for offline BM25 search. The excerpts remain
© Wolfram Research, Inc.; when quoting them, cite the source URL on
<https://reference.wolfram.com>.

## Modelica Standard Library reference (`msl.json`)

- **Title:** Modelica Standard Library (MSL), version 4.0.0
- **Author / publisher:** Modelica Association and contributors
- **Source:** <https://github.com/modelica/ModelicaStandardLibrary>
- **Copyright:** © 1998–2020 Modelica Association and contributors
- **License:** BSD 3-Clause —
  <https://github.com/modelica/ModelicaStandardLibrary/blob/master/LICENSE>

`msl.json` contains the embedded class documentation and source code of the
Modelica Standard Library (the `Modelica` package and the accompanying
`ModelicaReference` library from the same MSL 4.0.0 distribution), one
retrieval chunk per class. **Changes were made:** HTML documentation was
flattened to plain text (figures dropped), graphical/placement annotations
were stripped from the source code, and boilerplate classes (those extending
`Modelica.Icons.Contact`/`.ReleaseNotes`/`.References`) were omitted. Chunks
are keyed by `modelica://<TopPackage>/<Name>` pseudo-URLs.

As required by the BSD 3-Clause license, the full license text is reproduced
below:

> Copyright (c) 1998-2020, Modelica Association and contributors
> All rights reserved.
>
> Redistribution and use in source and binary forms, with or without
> modification, are permitted provided that the following conditions are met:
>
> 1. Redistributions of source code must retain the above copyright notice,
>    this list of conditions and the following disclaimer.
>
> 2. Redistributions in binary form must reproduce the above copyright notice,
>    this list of conditions and the following disclaimer in the documentation
>    and/or other materials provided with the distribution.
>
> 3. Neither the name of the copyright holder nor the names of its
>    contributors may be used to endorse or promote products derived from this
>    software without specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
> AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
> IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
> ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
> LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
> CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
> SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
> INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
> CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
> ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
> POSSIBILITY OF SUCH DAMAGE.

"Modelica" is a registered trademark of the Modelica Association.

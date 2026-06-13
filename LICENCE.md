# SVR4-reborn Licence

## Preface

The copyright and licence situation of the repository is complicated, due to the projects base being the AT&T UNIX System V Kernel, specifically Release 4, (likely) Version 2.1.
The original code was, at the time, not meant to be released. Indeed, almost all source files contain proprietary code disclaimers.
However:
- The original code is ~35 years old now
- The exact owner of this code is not clear, and no one has attempted to enforce copyright of this code in a long time.
- Some original derivatives, such as OpenSolaris, released their source code, which decends from the original AT&T source code.
- This original tree has been archived and public for a long time, both on public Git repos, and in Tarball form, for a while now.
- Older (<= v7) UNIX kernels have been open sourced 

It is therefore safe to assume that this code is abandaonware. While this status does not mean this work isn't under copyright by *someone*, it does mean that the non-commercial use in this project is unlikely to cause any issues. Therefore, this repo does ***not claim copyright of any kind over the original unmodified AT&T source code.***

For specific information regarding a indivudal file, check the file itself. Original AT&T code will keep its headers, significantly-modified-but-based-on files and entirely new files will both have custom headers containing copyright information.

## Non-AT&T code licence

All non-AT&T code is licenced under MIT:

```
Copyright 2026 Alex Richards

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## AT&T code modifications

As far as is legally possible, all changes to code are also licenced under MIT, see above.

The original copyright notice on-boot was the following:

```
AT&T UNIX System V/386 Release 4 Version 2.1 // Version fields filled in at build time
Copyright (c) 1984, 1986, 1987, 1988, 1989, 1990 AT&T
Copyright (c) 1990 UNIX System Laboratories, Inc.
Copyright (c) 1987, 1988 Microsoft Corp.
Copyright (c) 1986, 1987, 1988, 1989, 1990 Intel Corp. // on some build configurations only
All Rights Reserved
```


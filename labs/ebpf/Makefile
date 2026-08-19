CLANG ?= clang
LLVM_STRIP ?= llvm-strip
BPFTOOL ?= bpftool

ARCH := $(shell uname -m | sed 's/x86_64/x86/')

INCLUDES := -I../../ -I/usr/include/$(shell uname -m)-linux-gnu

all: offcpu_profiler.bpf.o

%.bpf.o: %.c
	$(CLANG) -g -O2 -target bpf -D__TARGET_ARCH_$(ARCH) $(INCLUDES) -c $< -o $@
	$(LLVM_STRIP) -g $@

clean:
	rm -f *.bpf.o

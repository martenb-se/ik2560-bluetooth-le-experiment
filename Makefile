# Documentation:
# Patterns - https://www.gnu.org/software/make/manual/html_node/Pattern-Rules.html
# Ordered prerequisites - https://www.gnu.org/software/make/manual/html_node/Prerequisite-Types.html

# Programs
GCC = gcc

# C Linking
C_LINK_BLUEZ = -lbluetooth
C_LINK_PTHREAD = -lpthread

# Arguments
all: l2cap-client l2cap-server

# Cleanup
clean:
	find . -name '*.o' -delete

# Programs
l2cap-client: l2cap-client.c | build-dir
	$(GCC) -o build/$@ $(word 2,$^) $< $(C_LINK_BLUEZ) $(C_LINK_PTHREAD)

l2cap-server: l2cap-server.c | build-dir
	$(GCC) -o build/$@ $(word 2,$^) $< $(C_LINK_BLUEZ) $(C_LINK_PTHREAD)

# Prerequisites
build-dir:
	mkdir -p build

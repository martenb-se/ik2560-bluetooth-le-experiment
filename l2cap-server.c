/**
 * Code is modified from:
 * https://people.csail.mit.edu/albert/bluez-intro/x559.html#l2cap-server.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <bluetooth/bluetooth.h>
#include <bluetooth/l2cap.h>
#include <bluetooth/hci.h>
#include <bluetooth/hci_lib.h>
#include <sys/ioctl.h>

/**
 * From https://github.com/pauloborges/bluez/blob/master/tools/hcitool.c#L77
 * Display addresses for the Bluetooth adapters on the device.
 */
static int dev_info(int s, int dev_id, long arg)
{
    struct hci_dev_info di = { .dev_id = dev_id };
    char addr[18];

    if (ioctl(s, HCIGETDEVINFO, (void *) &di))
    return 0;

    ba2str(&di.bdaddr, addr);
    printf("\t%s\t%s\n", di.name, addr);
    return 0;
}

int main(int argc, char **argv)
{
    struct sockaddr_l2 loc_addr = { 0 }, rem_addr = { 0 };
    char buf[1024] = { 0 };
    int s, client;
    long bytes_read, status;
    socklen_t opt = sizeof(rem_addr);
    char *message = "hello from server!";

    printf("Devices:\n");
    hci_for_each_dev(HCI_UP, dev_info, 0);

    // allocate socket
    s = socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);

    // bind socket to port 0x1001 of the first available
    // bluetooth adapter
    loc_addr.l2_family = AF_BLUETOOTH;
    loc_addr.l2_bdaddr = *BDADDR_ANY;
    loc_addr.l2_psm = htobs(0x1001);

    status = bind(s, (struct sockaddr *)&loc_addr, sizeof(loc_addr));

    if(status != 0 ) {
        fprintf(stderr, "bind failed\n");
        exit(2);
    }

    // put socket into listening mode
    listen(s, 1);

    // accept one connection
    client = accept(s, (struct sockaddr *)&rem_addr, &opt);

    ba2str( &rem_addr.l2_bdaddr, buf );
    fprintf(stderr, "accepted connection from %s\n", buf);

    memset(buf, 0, sizeof(buf));

    // read data from the client
    bytes_read = read(client, buf, sizeof(buf));
    if( bytes_read > 0 ) {
        printf("received [%s]\n", buf);
    }

    // send message back
    status = write(client, message, 18);

    if( status < 0 ) perror("uh oh");

    // close connection
    close(client);
    close(s);
}

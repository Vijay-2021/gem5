#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <linux/nvme_ioctl.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define NVME_IOCTL_ADMIN_CMD _IOWR('N', 0x41, struct nvme_admin_cmd)

int main(int argc, char **argv) {
    int fd = open("/dev/nvme0", O_RDWR);
    if (fd < 0) {
        perror("open");
        return 1;
    }

    struct nvme_admin_cmd cmd;
    memset(&cmd, 0, sizeof(cmd));

    cmd.opcode = 0xC1; // Replace with your custom opcode
    cmd.nsid = 0;      // 0 for Admin commands
    cmd.addr = (intptr_t)NULL; // Replace with buffer address if needed
    cmd.data_len = 0;  // Replace with data length if needed
    cmd.cdw10 = 0;     // Set as required
    cmd.cdw11 = 0;     // Set as required

    int err = ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd);
    if (err < 0) {
        perror("ioctl");
        close(fd);
        return 1;
    }
    cmd.opcode = 0xC2;
    err = ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd);
    if (err < 0) {
        perror("ioctl");
        close(fd);
        return 1;
    }
    cmd.opcode = 0xC3;
    err = ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd);
    if (err < 0) {
        perror("ioctl");
        close(fd);
        return 1;
    }

    cmd.opcode = 0xC4; // Replace with your custom opcode
    err = ioctl(fd, NVME_IOCTL_ADMIN_CMD, &cmd);
    if (err < 0) {
        perror("ioctl");
        close(fd);
        return 1;
    }

    printf("Command completed successfully.\n");
    close(fd);
    return 0;
}

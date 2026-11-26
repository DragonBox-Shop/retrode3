/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
int retrode_port_open(void);
void retrode_port_close(void);
int retrode_sdio_unbind(void);
int retrode_sdio_bind(void);
int retrode_port_failed(void);

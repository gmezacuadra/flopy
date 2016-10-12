from __future__ import print_function
import os
import numpy as np
from .binaryfile import CellBudgetFile


class Budget(object):
    """
    ZoneBudget Budget class. This is a wrapper around a numpy record array to allow users
    to save the record array to a formatted csv file.
    """
    def __init__(self, records, **kwargs):
        self.records = records
        # if 'kstpkper' in kwargs.keys():
        #     self.kstpkper =
        # self.kstpkper = kstpkper
        # self.totim = totim
        # assert(self.kstpkper is not None or self.totim is not None), 'Budget object requires either kstpkper ' \
        #                                                              'or totim be be specified.'
        self.kwargs = kwargs
        # List the field names to be used to slice the recarray
        # fields = ['ZONE{: >4d}'.format(z) for z in self.zones]
        fields = [name for name in self.records.dtype.names if 'ZONE' in name]

        self.ins_idx = np.where(self.records['flow_dir'] == 'in')[0]
        self.out_idx = np.where(self.records['flow_dir'] == 'out')[0]

        ins = _fields_view(self.records[self.ins_idx], fields)
        out = _fields_view(self.records[self.out_idx], fields)

        self.ins_sum = ins.sum(axis=0)
        self.out_sum = out.sum(axis=0)

        self.ins_minus_out = self.ins_sum - self.out_sum
        self.ins_plus_out = self.ins_sum + self.out_sum

        pcterr = 100 * self.ins_minus_out / (self.ins_plus_out / 2.)
        self.pcterr = np.array([i if not np.isnan(i) else 0 for i in pcterr])

    def get_total_inflow(self):
        return self.ins_sum

    def get_total_outflow(self):
        return self.out_sum

    def get_percent_error(self):
        return self.pcterr

    def to_csv(self, fname, write_format='pandas', formatter=None):
        """
        Saves the Budget object record array to a formatted csv file.

        Parameters
        ----------
        fname
        write_format
        formatter

        Returns
        -------

        """
        assert write_format.lower() in ['pandas', 'zonbud'], 'Format must be one of "pandas" or "zonbud".'

        if formatter is None:
            formatter = '{:.16e}'.format

        if write_format.lower() == 'pandas':
            with open(fname, 'w') as f:

                # Write header
                f.write(','.join(self.records.dtype.names)+'\n')

                # Write IN terms
                for rec in self.records[self.ins_idx]:
                    items = []
                    for i in rec:
                        if isinstance(i, str):
                            items.append(i)
                        else:
                            items.append(formatter(i))
                    f.write(','.join(items)+'\n')
                f.write(','.join([' ', 'Total IN'] + [formatter(i) for i in self.ins_sum])+'\n')

                # Write OUT terms
                for rec in self.records[self.out_idx]:
                    items = []
                    for i in rec:
                        if isinstance(i, str):
                            items.append(i)
                        else:
                            items.append(formatter(i))
                    f.write(','.join(items) + '\n')
                f.write(','.join([' ', 'Total OUT'] + [formatter(i) for i in self.out_sum])+'\n')

                # Write mass balance terms
                f.write(','.join([' ', 'IN-OUT'] + [formatter(i) for i in self.ins_minus_out])+'\n')
                f.write(','.join([' ', 'Percent Error'] + [formatter(i) for i in self.pcterr])+'\n')

        elif write_format.lower() == 'zonbud':
            with open(fname, 'w') as f:

                # Write header
                if 'kstpkper' in self.kwargs.keys():
                    header = 'Time Step, {kstp}, Stress Period, {kper}\n'.format(kstp=self.kwargs['kstpkper'][0]+1,
                                                                                 kper=self.kwargs['kstpkper'][1]+1)
                elif 'totim' in self.kwargs.keys():
                    header = 'Sim. Time, {totim}\n'.format(totim=self.kwargs['totim'])
                else:
                    raise Exception('No stress period/time step or time specified.')

                f.write(header)
                f.write(','.join([' '] + [field for field in self.records.dtype.names[2:]])+'\n')

                # Write IN terms
                f.write(','.join([' '] + ['IN']*(len(self.records.dtype.names[1:])-1))+'\n')
                for rec in self.records[self.ins_idx]:
                    items = []
                    for i in list(rec)[1:]:
                        if isinstance(i, str):
                            items.append(i)
                        else:
                            items.append(formatter(i))
                    f.write(','.join(items)+'\n')
                f.write(','.join(['Total IN'] + [formatter(i) for i in self.ins_sum])+'\n')

                # Write OUT terms
                f.write(','.join([' '] + ['OUT']*(len(self.records.dtype.names[1:])-1))+'\n')
                for rec in self.records[self.out_idx]:
                    items = []
                    for i in list(rec)[1:]:
                        if isinstance(i, str):
                            items.append(i)
                        else:
                            items.append(formatter(i))
                    f.write(','.join(items) + '\n')
                f.write(','.join(['Total OUT'] + [formatter(i) for i in self.out_sum])+'\n')

                # Write mass balance terms
                f.write(','.join(['IN-OUT'] + [formatter(i) for i in self.ins_minus_out])+'\n')
                f.write(','.join(['Percent Error'] + [formatter(i) for i in self.pcterr])+'\n')


class ZoneBudget(object):
    """
    ZoneBudget class

    Example usage:

    >>>from flopy.utils import ZoneBudget
    >>>zb = ZoneBudget('zonebudtest.cbc')
    >>>bud = zb.get_budget('GWBasins.zon', kstpkper=(0, 0))
    >>>bud.to_csv('zonebudtest.csv')
    """
    def __init__(self, cbc_file):

        # INTERNAL FLOW TERMS ARE USED TO CALCULATE FLOW BETWEEN ZONES.
        # CONSTANT-HEAD TERMS ARE USED TO IDENTIFY WHERE CONSTANT-HEAD CELLS ARE AND THEN USE
        # FACE FLOWS TO DETERMINE THE AMOUNT OF FLOW.
        # SWIADDTO* terms are used by the SWI2 package.
        internal_flow_terms = ['CONSTANT HEAD', 'FLOW RIGHT FACE', 'FLOW FRONT FACE', 'FLOW LOWER FACE']

        if isinstance(cbc_file, CellBudgetFile):
            self.cbc = cbc_file
        elif isinstance(cbc_file, str) and os.path.isfile(cbc_file):
            self.cbc = CellBudgetFile(cbc_file)
        else:
            raise Exception('Cannot load cell budget file.')

        # All record names in the cell-by-cell budget binary file
        self.record_names = [n.strip() for n in self.cbc.unique_record_names()]

        # Get imeth for each record in the CellBudgetFile record list
        self.imeth = {}
        for record in self.cbc.recordarray:
            self.imeth[record['text'].strip()] = record['imeth']

        # Internal flow record names
        self.ift_record_names = [n.strip() for n in self.cbc.unique_record_names()
                                 if n.strip() in internal_flow_terms]

        # Source/sink/storage term record names
        # These are all of the terms left over that are not related to constant
        # head cells or face flow terms
        self.ssst_record_names = [n.strip() for n in self.cbc.unique_record_names()
                                  if n.strip() not in self.ift_record_names]

        # Check the shape of the cbc budget file arrays
        self.cbc_shape = self.get_model_shape()
        self.nlay, self.nrow, self.ncol = self.cbc_shape

        self.float_type = np.float64
        return

    def get_model_shape(self):
        l, r, c = self.cbc.get_data(idx=0, full3D=True)[0].shape
        return l, r, c

    def get_budget(self, z, **kwargs):
        """
        Creates a budget for the specified zone array. Pass keyword arguments to specify
        the time step/stress period or sim. time for which a budget is desired.

        :param z: A numpy.ndarray containing to zones to be used.
        :param kwargs:
        :return:
        Budget object
        """
        if 'kstpkper' in kwargs.keys():
            s = 'The specified time step/stress period' \
                ' does not exist {}'.format(kwargs['kstpkper'])
            assert kwargs['kstpkper'] in self.cbc.get_kstpkper(), print(s)
        elif 'totim' in kwargs.keys():
            s = 'The time ' \
                ' does not exist {}'.format(kwargs['totim'])
            assert kwargs['kstpkper'] in self.cbc.get_times(), print(s)
        else:
            raise Exception('No stress period/time step or time specified.')
        assert isinstance(z, np.ndarray), 'Please pass zones as type {}'.format(np.ndarray)

        # Check for negative zone values
        negative_zones = [iz for iz in np.unique(z) if iz < 0]
        if len(negative_zones) > 0:
            raise Exception('Negative zone value(s) found:', negative_zones)

        # Make sure the input zone array has the same shape as the cell budget file
        if len(z.shape) == 2:
            izone = np.zeros(self.cbc_shape, np.int32)
            for i in range(izone.shape[0]):
                izone[i, :, :] = z
        else:
            izone = z.copy()

        assert izone.shape == self.cbc_shape, \
            'Shape of input zone array {} does not' \
            ' match the cell by cell' \
            ' budget file {}'.format(izone.shape, self.cbc_shape)

        # Initialize a constant head array
        ich = np.zeros(self.cbc_shape, np.int32)

        # Create empty arrays for the inflow and outflow terms.
        # These arrays have the structure: ('flow direction', 'record name', value zone 1, value zone 2, etc.)
        self._initialize_records(izone)

        # Create a throwaway list of all record names
        reclist = list(self.record_names)

        if 'CONSTANT HEAD' in reclist:
            reclist.remove('CONSTANT HEAD')
            chd = self.cbc.get_data(text='CONSTANT HEAD', full3D=True, **kwargs)[0]
            ich = np.zeros(self.cbc_shape, np.int32)
            ich[chd != 0] = 1
        if 'FLOW RIGHT FACE' in reclist:
            reclist.remove('FLOW RIGHT FACE')
            self._accumulate_flow_frf('FLOW RIGHT FACE', izone, ich, **kwargs)
        if 'FLOW FRONT FACE' in reclist:
            reclist.remove('FLOW FRONT FACE')
            self._accumulate_flow_fff('FLOW FRONT FACE', izone, ich, **kwargs)
        if 'FLOW LOWER FACE' in reclist:
            reclist.remove('FLOW LOWER FACE')
            self._accumulate_flow_flf('FLOW LOWER FACE', izone, ich, **kwargs)
        if 'SWIADDTOCH' in reclist:
            reclist.remove('SWIADDTOCH')
            swichd = self.cbc.get_data(text='SWIADDTOCH', full3D=True, **kwargs)[0]
            swiich = np.zeros(self.cbc_shape, np.int32)
            swiich[swichd != 0] = 1
        if 'SWIADDTOFRF' in reclist:
            reclist.remove('SWIADDTOFRF')
            self._accumulate_flow_frf('SWIADDTOFRF', izone, swiich, **kwargs)
        if 'SWIADDTOFFF' in reclist:
            reclist.remove('SWIADDTOFFF')
            self._accumulate_flow_fff('SWIADDTOFFF', izone, swiich, **kwargs)
        if 'SWIADDTOFLF' in reclist:
            reclist.remove('SWIADDTOFLF')
            self._accumulate_flow_flf('SWIADDTOFLF', izone, swiich, **kwargs)

        # NOT AN INTERNAL FLOW TERM, SO MUST BE A SOURCE TERM OR STORAGE
        # ACCUMULATE THE FLOW BY ZONE
        # iterate over remaining items in the list
        for recname in reclist:

            imeth = self.imeth[recname]
            data = self.cbc.get_data(text=recname, **kwargs)[0]

            if imeth == 2 or imeth == 5:
                # LIST
                budin = np.ma.zeros((self.nlay * self.nrow * self.ncol), self.float_type)
                budout = np.ma.zeros((self.nlay * self.nrow * self.ncol), self.float_type)
                for [node, q] in zip(data['node'], data['q']):
                    idx = node - 1
                    if q > 0:
                        budin.data[idx] += q
                    elif q < 0:
                        budout.data[idx] += q
                budin = np.ma.reshape(budin, (self.nlay, self.nrow, self.ncol))
                budout = np.ma.reshape(budout, (self.nlay, self.nrow, self.ncol))
                self._accumulate_ssst_flow(recname, budin, budout, izone)

            elif imeth == 0 or imeth == 1:
                # FULL 3-D ARRAY
                budin = np.ma.zeros(self.cbc_shape, self.float_type)
                budout = np.ma.zeros(self.cbc_shape, self.float_type)
                budin[data > 0] = data[data > 0]
                budout[data < 0] = data[data < 0]
                self._accumulate_ssst_flow(recname, budin, budout, izone)

            elif imeth == 3:
                # 1-LAYER ARRAY WITH LAYER INDICATOR ARRAY
                rlay, rdata = data[0], data[1]
                data = np.ma.zeros(self.cbc_shape, self.float_type)
                for (r, c), l in np.ndenumerate(rlay):
                    data[l - 1, r, c] = rdata[r, c]
                budin = np.ma.zeros(self.cbc_shape, self.float_type)
                budout = np.ma.zeros(self.cbc_shape, self.float_type)
                budin[data > 0] = data[data > 0]
                budout[data < 0] = data[data < 0]
                self._accumulate_ssst_flow(recname, budin, budout, izone)

            elif imeth == 4:
                # 1-LAYER ARRAY THAT DEFINES LAYER 1
                budin = np.ma.zeros(self.cbc_shape, self.float_type)
                budout = np.ma.zeros(self.cbc_shape, self.float_type)
                r, c = np.where(data > 0)
                budin[0, r, c] = data[r, c]
                r, c = np.where(data < 0)
                budout[0, r, c] = data[r, c]
                self._accumulate_ssst_flow(recname, budin, budout, izone)

        return Budget(self.zonbudrecords, **kwargs)

    def _build_empty_record(self, flow_dir, recname, izone):

        nzzones = [z for z in np.unique(izone) if z != 0]
        recs = np.array(tuple([flow_dir, recname] + [0. for _ in nzzones]),
                        dtype=self.zonbudrecords.dtype)
        self.zonbudrecords = np.append(self.zonbudrecords, recs)
        # recs = np.array(tuple(['in', recname] + [0. for _ in nzzones]),
        #                 dtype=self.inflows.dtype)
        # self.inflows = np.append(self.inflows, recs)
        # recs = np.array(tuple(['out', recname] + [0. for _ in nzzones]),
        #                 dtype=self.outflows.dtype)
        # self.outflows = np.append(self.outflows, recs)

    def _initialize_records(self, izone):
        zones = [z for z in np.unique(izone)]
        nzzones = [z for z in np.unique(izone) if z != 0]

        # Initialize the record array
        dtype_list = [('flow_dir', '|S3'), ('record', '|S20')]
        dtype_list += [('ZONE {:d}'.format(z), self.float_type) for z in nzzones]
        dtype = np.dtype(dtype_list)
        self.zonbudrecords = np.array([], dtype=dtype)

        # Add "in" records
        if 'CONSTANT HEAD' in self.record_names:
            self._build_empty_record('in', 'CONSTANT HEAD', izone)

        for recname in self.ssst_record_names:
            self._build_empty_record('in', recname, izone)

        # internal flow records
        for z in zones:
            self._build_empty_record('in', 'FROM ZONE {}'.format(z), izone)

        # Add "out" records
        if 'CONSTANT HEAD' in self.record_names:
            self._build_empty_record('out', 'CONSTANT HEAD', izone)

        for recname in self.ssst_record_names:
            self._build_empty_record('out', recname, izone)

        # internal flow records
        for z in zones:
            self._build_empty_record('out', 'TO ZONE {}'.format(z), izone)

        return

    def _update_record(self, flow_dir, recname, colname, flux):
        if colname != 'ZONE 0':
            rowidx = np.where((self.zonbudrecords['flow_dir'] == flow_dir) & (self.zonbudrecords['record'] == recname))
            self.zonbudrecords[colname][rowidx] += flux
        return

    def _accumulate_flow_frf(self, recname, izone, ich, **kwargs):
        # ACCUMULATE FLOW BETWEEN ZONES ACROSS COLUMNS. COMPUTE FLOW ONLY BETWEEN A ZONE
        # AND A HIGHER ZONE -- FLOW FROM ZONE 4 TO 3 IS THE NEGATIVE OF FLOW FROM 3 TO 4.
        # FIRST, CALCULATE FLOW BETWEEN NODE J,I,K AND J-1,I,K.
        # Accumulate flow from lower zones to higher zones from "left" to "right".
        # Flow into the higher zone will be <0 Flow Right Face from the adjacent cell to the "left".
        bud = self.cbc.get_data(text=recname, **kwargs)[0]

        nz = izone[:, :, 1:]
        nzl = izone[:, :, :-1]
        l, r, c = np.where(nz > nzl)

        # Adjust column values to account for the starting position of "nz"
        c += 1

        # Define the zone from which flow is coming
        from_zones = izone[l, r, c-1]

        # Define the zone to which flow is going
        to_zones = izone[l, r, c]

        # Get the face flow
        q = bud[l, r, c - 1]

        # Don't include CH to CH flow (can occur if CHTOCH option is used)
        q[(ich[l, r, c] == 1) & (ich[l, r, c-1] == 1)] = 0.

        # Get indices where flow face values are negative (flow into higher zone)
        idx_neg = np.where(q < 0)

        # Get indices where flow face values are positive (flow out of higher zone)
        idx_pos = np.where(q >= 0)

        # Create tuples of ("to zone", "from zone", "absolute flux")
        neg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        pos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        nzgt_l2r = neg + pos

        # CALCULATE FLOW TO CONSTANT-HEAD CELLS IN THIS DIRECTION
        l, r, c = np.where(ich == 1)

        # Can't accumulate left-to-right for cells on left edge of model (c = 0)
        l, r, c = l[c > 0], r[c > 0], c[c > 0]

        from_zones = izone[l, r, c-1]
        to_zones = izone[l, r, c]
        q = bud[l, r, c-1]
        q[(ich[l, r, c] == 1) & (ich[l, r, c-1] == 1)] = 0.
        idx_neg = np.where(q < 0)
        idx_pos = np.where(q >= 0)
        chdneg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        chdpos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        for (from_zone, to_zone, flux) in chdneg:
            self._update_record('in', 'CONSTANT HEAD', 'ZONE {}'.format(to_zone), flux)
        for (from_zone, to_zone, flux) in chdpos:
            self._update_record('out', 'CONSTANT HEAD', 'ZONE {}'.format(from_zone), flux)

        # CALCULATE FLOW BETWEEN NODE J,I,K AND J+1,I,K.
        # Accumulate flow from lower zones to higher zones from "right" to "left".
        # Flow into the higher zone will be <0 Flow Right Face from the adjacent cell to the "left".
        nz = izone[:, :, :-1]
        nzr = izone[:, :, 1:]
        l, r, c = np.where(nz > nzr)

        # Define the zone from which flow is coming
        from_zones = izone[l, r, c]

        # Define the zone to which flow is going
        to_zones = izone[l, r, c+1]

        # Get the face flow
        q = bud[l, r, c]

        # Don't include CH to CH flow (can occur if CHTOCH option is used)
        q[(ich[l, r, c] == 1) & (ich[l, r, c+1] == 1)] = 0.

        # Get indices where flow face values are negative (flow into higher zone)
        idx_neg = np.where(q < 0)

        # Get indices where flow face values are positive (flow out of higher zone)
        idx_pos = np.where(q >= 0)

        # Create tuples of ("to zone", "from zone", "absolute flux")
        neg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        pos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        nzgt_r2l = neg + pos

        # CALCULATE FLOW TO CONSTANT-HEAD CELLS IN THIS DIRECTION
        l, r, c = np.where(ich == 1)

        # Can't accumulate right-to-left for cells on right edge of model (c = ncol)
        l, r, c = l[c < self.ncol-1], r[c < self.ncol-1], c[c < self.ncol-1]

        from_zones = izone[l, r, c]
        to_zones = izone[l, r, c+1]
        q = bud[l, r, c]
        q[(ich[l, r, c] == 1) & (ich[l, r, c+1] == 1)] = 0.
        idx_neg = np.where(q < 0)
        idx_pos = np.where(q >= 0)
        chdneg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        chdpos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        for (from_zone, to_zone, flux) in chdneg:
            self._update_record('in', 'CONSTANT HEAD', 'ZONE {}'.format(to_zone), flux)
        for (from_zone, to_zone, flux) in chdpos:
            self._update_record('out', 'CONSTANT HEAD', 'ZONE {}'.format(from_zone), flux)

        # Update records
        nzgt = nzgt_l2r + nzgt_r2l
        for (from_zone, to_zone, flux) in nzgt:
            self._update_record('in', 'FROM ZONE {}'.format(from_zone), 'ZONE {}'.format(to_zone), flux)
            self._update_record('out', 'TO ZONE {}'.format(to_zone), 'ZONE {}'.format(from_zone), flux)
        return

    def _accumulate_flow_fff(self, recname, izone, ich, **kwargs):
        # ACCUMULATE FLOW BETWEEN ZONES ACROSS ROWS. COMPUTE FLOW ONLY BETWEEN A ZONE
        #  AND A HIGHER ZONE -- FLOW FROM ZONE 4 TO 3 IS THE NEGATIVE OF FLOW FROM 3 TO 4.
        # FIRST, CALCULATE FLOW BETWEEN NODE J,I,K AND J,I-1,K.
        # Accumulate flow from lower zones to higher zones from "up" to "down".
        # Returns a tuple of ("to zone", "from zone", "absolute flux")
        bud = self.cbc.get_data(text=recname, **kwargs)[0]

        nz = izone[:, 1:, :]
        nzu = izone[:, :-1, :]
        l, r, c = np.where(nz < nzu)
        # Adjust column values by +1 to account for the starting position of "nz"
        r += 1

        # Define the zone from which flow is coming
        from_zones = izone[l, r-1, c]

        # Define the zone to which flow is going
        to_zones = izone[l, r, c]

        # Get the face flow
        q = bud[l, r-1, c]

        # Don't include CH to CH flow (can occur if CHTOCH option is used)
        q[(ich[l, r, c] == 1) & (ich[l, r-1, c] == 1)] = 0.

        # Get indices where flow face values are negative (flow into higher zone)
        idx_neg = np.where(q < 0)

        # Get indices where flow face values are positive (flow out of higher zone)
        idx_pos = np.where(q >= 0)

        # Create tuples of ("to zone", "from zone", "absolute flux")
        neg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        pos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        nzgt_u2d = neg + pos

        # CALCULATE FLOW TO CONSTANT-HEAD CELLS IN THIS DIRECTION
        l, r, c = np.where(ich == 1)

        # Can't accumulate up-to-down for cells on top edge of model (r = 0)
        l, r, c = l[r > 0], r[r > 0], c[r > 0]

        from_zones = izone[l, r-1, c]
        to_zones = izone[l, r, c]
        q = bud[l, r-1, c]
        q[(ich[l, r, c] == 1) & (ich[l, r-1, c] == 1)] = 0.
        idx_neg = np.where(q < 0)
        idx_pos = np.where(q >= 0)
        chdneg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        chdpos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        for (from_zone, to_zone, flux) in chdneg:
            self._update_record('in', 'CONSTANT HEAD', 'ZONE {}'.format(to_zone), flux)
        for (from_zone, to_zone, flux) in chdpos:
            self._update_record('out', 'CONSTANT HEAD', 'ZONE {}'.format(from_zone), flux)

        # CALCULATE FLOW BETWEEN NODE J,I,K AND J,I+1,K.
        # Accumulate flow from lower zones to higher zones from "down" to "up".
        nz = izone[:, :-1, :]
        nzd = izone[:, 1:, :]
        l, r, c = np.where(nz < nzd)

        # Define the zone from which flow is coming
        from_zones = izone[l, r, c]

        # Define the zone to which flow is going
        to_zones = izone[l, r+1, c]

        # Get the face flow
        q = bud[l, r, c]

        # Don't include CH to CH flow (can occur if CHTOCH option is used)
        q[(ich[l, r, c] == 1) & (ich[l, r+1, c] == 1)] = 0.

        # Get indices where flow face values are negative (flow into higher zone)
        idx_neg = np.where(q < 0)

        # Get indices where flow face values are positive (flow out of higher zone)
        idx_pos = np.where(q >= 0)

        # Create tuples of ("to zone", "from zone", "absolute flux")
        neg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        pos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        nzgt_d2u = neg + pos

        # CALCULATE FLOW TO CONSTANT-HEAD CELLS IN THIS DIRECTION
        l, r, c = np.where(ich == 1)

        # Can't accumulate down-to-up for cells on bottom edge of model (r = nrow)
        l, r, c = l[r < self.nrow-1], r[r < self.nrow-1], c[r < self.nrow-1]

        from_zones = izone[l, r, c]
        to_zones = izone[l, r+1, c]
        q = bud[l, r, c]
        q[(ich[l, r, c] == 1) & (ich[l, r+1, c] == 1)] = 0.
        idx_neg = np.where(q < 0)
        idx_pos = np.where(q >= 0)
        chdneg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        chdpos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        for (from_zone, to_zone, flux) in chdneg:
            self._update_record('in', 'CONSTANT HEAD', 'ZONE {}'.format(to_zone), flux)
        for (from_zone, to_zone, flux) in chdpos:
            self._update_record('out', 'CONSTANT HEAD', 'ZONE {}'.format(from_zone), flux)

        # Update records
        nzgt = nzgt_u2d + nzgt_d2u
        for (from_zone, to_zone, flux) in nzgt:
            self._update_record('in', 'FROM ZONE {}'.format(from_zone), 'ZONE {}'.format(to_zone), flux)
            self._update_record('out', 'TO ZONE {}'.format(to_zone), 'ZONE {}'.format(from_zone), flux)
        return

    def _accumulate_flow_flf(self, recname, izone, ich, **kwargs):
        # ACCUMULATE FLOW BETWEEN ZONES ACROSS LAYERS. COMPUTE FLOW ONLY BETWEEN A ZONE
        #  AND A HIGHER ZONE -- FLOW FROM ZONE 4 TO 3 IS THE NEGATIVE OF FLOW FROM 3 TO 4.
        # FIRST, CALCULATE FLOW BETWEEN NODE J,I,K AND J,I,K-1.
        # Accumulate flow from lower zones to higher zones from "top" to "bottom".
        # Returns a tuple of ("to zone", "from zone", "absolute flux")
        bud = self.cbc.get_data(text=recname, **kwargs)[0]

        nz = izone[1:, :, :]
        nzt = izone[:-1, :, :]
        l, r, c = np.where(nz > nzt)
        # Adjust column values by +1 to account for the starting position of "nz"
        l += 1

        # Define the zone from which flow is coming
        from_zones = izone[l-1, r, c]

        # Define the zone to which flow is going
        to_zones = izone[l, r, c]

        # Get the face flow
        q = bud[l-1, r, c]

        # Don't include CH to CH flow (can occur if CHTOCH option is used)
        q[(ich[l, r, c] == 1) & (ich[l-1, r, c] == 1)] = 0.

        # Get indices where flow face values are negative (flow into higher zone)
        idx_neg = np.where(q < 0)

        # Get indices where flow face values are positive (flow out of higher zone)
        idx_pos = np.where(q >= 0)

        # Create tuples of ("to zone", "from zone", "absolute flux")
        neg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        pos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        nzgt_t2b = neg + pos

        # CALCULATE FLOW TO CONSTANT-HEAD CELLS IN THIS DIRECTION
        l, r, c = np.where(ich == 1)

        # Can't accumulate top-to-bottom for cells at top edge of model (l = 0)
        l, r, c = l[l > 0], r[l > 0], c[l > 0]

        from_zones = izone[l-1, r, c]
        to_zones = izone[l, r, c]
        q = bud[l-1, r, c]
        q[(ich[l, r, c] == 1) & (ich[l-1, r, c] == 1)] = 0.
        idx_neg = np.where(q < 0)
        idx_pos = np.where(q >= 0)
        chdneg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        chdpos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        for (from_zone, to_zone, flux) in chdneg:
            self._update_record('in', 'CONSTANT HEAD', 'ZONE {}'.format(to_zone), flux)
        for (from_zone, to_zone, flux) in chdpos:
            self._update_record('out', 'CONSTANT HEAD', 'ZONE {}'.format(from_zone), flux)

        # CALCULATE FLOW BETWEEN NODE J,I,K AND J+1,I,K.
        # Accumulate flow from lower zones to higher zones from "right" to "left".
        # Flow into the higher zone will be <0 Flow Right Face from the adjacent cell to the "left".
        nz = izone[:-1, :, :]
        nzb = izone[1:, :, :]
        l, r, c = np.where(nz < nzb)

        # Define the zone from which flow is coming
        from_zones = izone[l, r, c]

        # Define the zone to which flow is going
        to_zones = izone[l+1, r, c]

        # Get the face flow
        q = bud[l, r, c]

        # Don't include CH to CH flow (can occur if CHTOCH option is used)
        q[(ich[l, r, c] == 1) & (ich[l+1, r, c] == 1)] = 0.

        # Get indices where flow face values are negative (flow into higher zone)
        idx_neg = np.where(q < 0)

        # Get indices where flow face values are positive (flow out of higher zone)
        idx_pos = np.where(q >= 0)

        # Create tuples of ("to zone", "from zone", "absolute flux")
        neg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        pos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        nzgt_b2t = neg + pos

        # CALCULATE FLOW TO CONSTANT-HEAD CELLS IN THIS DIRECTION
        l, r, c = np.where(ich == 1)

        # Can't accumulate bottom-to-top for cells at bottom edge of model (l = nlay)
        l, r, c = l[l < self.nlay - 1], r[l < self.nlay - 1], c[l < self.nlay - 1]

        from_zones = izone[l, r, c]
        to_zones = izone[l+1, r, c]
        q = bud[l, r, c]
        q[(ich[l, r, c] == 1) & (ich[l+1, r, c] == 1)] = 0.
        idx_neg = np.where(q < 0)
        idx_pos = np.where(q >= 0)
        chdneg = zip(to_zones[idx_neg], from_zones[idx_neg], np.abs(q[idx_neg]))
        chdpos = zip(from_zones[idx_pos], to_zones[idx_pos], np.abs(q[idx_pos]))
        for (from_zone, to_zone, flux) in chdneg:
            self._update_record('in', 'CONSTANT HEAD', 'ZONE {}'.format(to_zone), flux)
        for (from_zone, to_zone, flux) in chdpos:
            self._update_record('out', 'CONSTANT HEAD', 'ZONE {}'.format(from_zone), flux)

        # Update records
        nzgt = nzgt_t2b + nzgt_b2t
        for (from_zone, to_zone, flux) in nzgt:
            self._update_record('in', 'FROM ZONE {}'.format(from_zone), 'ZONE {}'.format(to_zone), flux)
            self._update_record('out', 'TO ZONE {}'.format(to_zone), 'ZONE {}'.format(from_zone), flux)
        return

    def _accumulate_ssst_flow(self, recname, budin, budout, izone):
        zones = [z for z in np.unique(izone)]
        recin = [np.abs(budin[(izone == z)].sum()) for z in np.unique(izone.ravel())]
        recout = [np.abs(budout[(izone == z)].sum()) for z in np.unique(izone.ravel())]
        for idx, flux in enumerate(recin):
            if type(flux) == np.ma.core.MaskedConstant:
                flux = 0.
            self._update_record('in', recname, 'ZONE {}'.format(zones[idx]), flux)
        for idx, flux in enumerate(recout):
            if type(flux) == np.ma.core.MaskedConstant:
                flux = 0.
            self._update_record('out', recname, 'ZONE {}'.format(zones[idx]), flux)
        return

    def get_kstpkper(self):
        return self.cbc.get_kstpkper()

    def get_times(self):
        return self.cbc.get_times()

    def get_indices(self):
        return self.cbc.get_indices()


def _fields_view(a, fields):
    new = a[fields].view(np.float64).reshape(a.shape + (-1,))
    return new

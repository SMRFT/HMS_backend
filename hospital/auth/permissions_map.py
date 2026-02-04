PAGE_MAPPING = {

    # ==================== ADMISSION ====================
    r'^/_b_a_c_k_e_n_d/HMS/doctor_list_diagnostics/?(\?.*)?$': 'HMS-P-DLD',
    r'^/_b_a_c_k_e_n_d/HMS/autoipNumber/?(\?.*)?$': 'HMS-P-AIN',
    r'^/_b_a_c_k_e_n_d/HMS/admission/?(\?.*)?$': 'HMS-P-ADM',
    r'^/_b_a_c_k_e_n_d/HMS/admission/[^/]+/?(\?.*)?$': 'HMS-P-ADD',
    r'^/_b_a_c_k_e_n_d/HMS/op-patient/[^/]+/?(\?.*)?$': 'HMS-P-OPP',
    r'^/_b_a_c_k_e_n_d/HMS/search-rooms/?(\?.*)?$': 'HMS-P-SRM',

    # ==================== PHARMACY STOCK ====================
    r'^/_b_a_c_k_e_n_d/HMS/ip-pharmacy-stock/?(\?.*)?$': 'HMS-P-IPPS',
    r'^/_b_a_c_k_e_n_d/HMS/ip-pharmacy-stock/[^/]+/?(\?.*)?$': 'HMS-P-IPPSD',
    r'^/_b_a_c_k_e_n_d/HMS/op-pharmacy-stock/?(\?.*)?$': 'HMS-P-OPPS',
    r'^/_b_a_c_k_e_n_d/HMS/op-pharmacy-stock/[^/]+/?(\?.*)?$': 'HMS-P-OPPSD',

    # ==================== GRN ====================
    r'^/_b_a_c_k_e_n_d/HMS/ip-grn/?(\?.*)?$': 'HMS-P-IPGRN',
    r'^/_b_a_c_k_e_n_d/HMS/ip-grn/[^/]+/?(\?.*)?$': 'HMS-P-IPGRND',
    r'^/_b_a_c_k_e_n_d/HMS/op-grn/?(\?.*)?$': 'HMS-P-OPGRN',
    r'^/_b_a_c_k_e_n_d/HMS/op-grn/[^/]+/?(\?.*)?$': 'HMS-P-OPGRND',

    # ==================== VENDOR ====================
    r'^/_b_a_c_k_e_n_d/HMS/vendor/?(\?.*)?$': 'HMS-P-VND',
    r'^/_b_a_c_k_e_n_d/HMS/vendor/[^/]+/?(\?.*)?$': 'HMS-P-VNDD',

    # ==================== ROOMS ====================
    r'^/_b_a_c_k_e_n_d/HMS/block/?(\?.*)?$': 'HMS-P-BLK',
    r'^/_b_a_c_k_e_n_d/HMS/block/[0-9]+/?(\?.*)?$': 'HMS-P-BLKD',
    r'^/_b_a_c_k_e_n_d/HMS/room-category/?(\?.*)?$': 'HMS-P-RCAT',
    r'^/_b_a_c_k_e_n_d/HMS/room-category/[0-9]+/?(\?.*)?$': 'HMS-P-RCATD',
    r'^/_b_a_c_k_e_n_d/HMS/room/?(\?.*)?$': 'HMS-P-RM',
    r'^/_b_a_c_k_e_n_d/HMS/room/[0-9]+/?(\?.*)?$': 'HMS-P-RMD',
    r'^/_b_a_c_k_e_n_d/HMS/bed/?(\?.*)?$': 'HMS-P-BED',
    r'^/_b_a_c_k_e_n_d/HMS/bed/[0-9]+/?(\?.*)?$': 'HMS-P-BEDD',
    r'^/_b_a_c_k_e_n_d/HMS/service/?(\?.*)?$': 'HMS-P-SRV',
    r'^/_b_a_c_k_e_n_d/HMS/service/[0-9]+/?(\?.*)?$': 'HMS-P-SRVD',
    r'^/_b_a_c_k_e_n_d/HMS/room-enquiry/?(\?.*)?$': 'HMS-P-RENQ',
    r'^/_b_a_c_k_e_n_d/HMS/room-shifting/?(\?.*)?$': 'HMS-P-RSHFT',

    # ==================== DISCHARGE ====================
    r'^/_b_a_c_k_e_n_d/HMS/search-admissions/?(\?.*)?$': 'HMS-P-SADM',
    r'^/_b_a_c_k_e_n_d/HMS/discharge/?(\?.*)?$': 'HMS-P-DIS',

    # ==================== NURSING ====================
    r'^/_b_a_c_k_e_n_d/HMS/room-shiftings/?(\?.*)?$': 'HMS-P-RSHFT',
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-uhid/[^/]+/?(\?.*)?$': 'HMS-P-AUHID',
    r'^/_b_a_c_k_e_n_d/HMS/admission-by-ip/[^/]+/?(\?.*)?$': 'HMS-P-AIP',
}


PAGE_ACTION_MAPPING = {
    'xxx': {
        'DELETE':'RWD',
    },
}

GEN_ACTION_MAPPING = {
    'POST': 'RW',
    'PUT': 'RW',
    'PATCH': 'RW',
    'DELETE': 'RW',
    'GET': 'R',
}




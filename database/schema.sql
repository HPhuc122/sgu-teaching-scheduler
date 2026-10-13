/* =====================================================================
   CSDL: He thong ho tro quan ly va phan cong giang day (UCTP)
   SQL Server - ban thiet ke tham chieu.
   Backend Django su dung migrations trong backend/school/migrations lam nguon
   trien khai. KHONG chay script nay va Django migrate tren cung mot CSDL:
   hai ban chua dong bo tat ca cot/constraint va bang auth cua Django.
   ===================================================================== */

CREATE DATABASE UCTP_DB;
GO
USE UCTP_DB;
GO

-- =====================================================================
-- 1. DANH MUC TO CHUC
-- =====================================================================

CREATE TABLE Khoa (
    MaKhoa          INT IDENTITY(1,1) PRIMARY KEY,
    TenKhoa         NVARCHAR(200) NOT NULL,
    MaKhoaVietTat   NVARCHAR(20) NOT NULL UNIQUE,
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME()
);

CREATE TABLE BoMon (
    MaBoMon         INT IDENTITY(1,1) PRIMARY KEY,
    MaKhoa          INT NOT NULL FOREIGN KEY REFERENCES Khoa(MaKhoa),
    TenBoMon        NVARCHAR(200) NOT NULL,
    TruongBoMonGVID INT NULL,  -- FK ve GiangVien, ALTER them sau khi tao bang GiangVien
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME()
);

-- =====================================================================
-- 2. GIANG VIEN
-- =====================================================================

CREATE TABLE GiangVien (
    MaGV            INT IDENTITY(1,1) PRIMARY KEY,
    MaBoMon         INT NOT NULL FOREIGN KEY REFERENCES BoMon(MaBoMon),
    MaVienChuc      NVARCHAR(30) NULL,           -- ma in tren bieu mau SGU; NULL cho GV chua co ma
    HoTen           NVARCHAR(200) NOT NULL,
    Email           NVARCHAR(200) NOT NULL UNIQUE,
    SoDienThoai     NVARCHAR(20)  NULL,
    HocVi           NVARCHAR(50)  NULL,           -- ThS, TS, PGS.TS,...
    SoTietToiThieu  INT NOT NULL DEFAULT 0,        -- dinh muc gio day toi thieu / hoc ky
    SoTietToiDa     INT NOT NULL DEFAULT 0,        -- dinh muc gio day toi da / hoc ky
    TrangThai       NVARCHAR(20)  NOT NULL DEFAULT N'DangCongTac',  -- DangCongTac, NghiPhep, DaNghi
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME()
);

CREATE UNIQUE INDEX UX_GiangVien_MaVienChuc ON GiangVien(MaVienChuc)
    WHERE MaVienChuc IS NOT NULL;

ALTER TABLE BoMon
    ADD CONSTRAINT FK_BoMon_TruongBoMon FOREIGN KEY (TruongBoMonGVID) REFERENCES GiangVien(MaGV);

-- =====================================================================
-- 3. HOC PHAN / LOP HOC PHAN / HOC KY
-- =====================================================================

CREATE TABLE HocPhan (
    MaHocPhan       INT IDENTITY(1,1) PRIMARY KEY,
    MaBoMon         INT NOT NULL FOREIGN KEY REFERENCES BoMon(MaBoMon),
    MaHocPhanCode   NVARCHAR(30)  NOT NULL UNIQUE,   -- vd: 'IT4409'
    TenHocPhan      NVARCHAR(200) NOT NULL,
    SoTinChi        INT NOT NULL,
    SoTietLyThuyet  INT NOT NULL DEFAULT 0,
    SoTietThucHanh  INT NOT NULL DEFAULT 0,
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME()
);

CREATE TABLE HocKy (
    MaHocKy         INT IDENTITY(1,1) PRIMARY KEY,
    TenHocKy        NVARCHAR(50) NOT NULL,      -- vd: 'HK1 2026-2027'
    NamHoc          NVARCHAR(20) NOT NULL,
    NgayBatDau      DATE NOT NULL,
    NgayKetThuc     DATE NOT NULL,
    SoTuan          INT NOT NULL,
    TrangThai       NVARCHAR(20) NOT NULL DEFAULT N'DangMo',  -- DangMo, DaKhoa
    CONSTRAINT CK_HocKy_SoTuan CHECK (SoTuan BETWEEN 1 AND 53),
    CONSTRAINT CK_HocKy_Ngay CHECK (NgayKetThuc >= NgayBatDau)
);

CREATE TABLE LopHocPhan (
    MaLopHP         INT IDENTITY(1,1) PRIMARY KEY,
    MaHocPhan       INT NOT NULL FOREIGN KEY REFERENCES HocPhan(MaHocPhan),
    MaHocKy         INT NOT NULL FOREIGN KEY REFERENCES HocKy(MaHocKy),
    MaLopCode       NVARCHAR(30) NOT NULL,      -- vd: 'IT4409.01'
    Nhom            NVARCHAR(10) NOT NULL,      -- nhom hoc phan in tren mau SGU
    ToTH            NVARCHAR(10) NULL,          -- to thuc hanh; NULL neu khong co
    LoaiLop         NVARCHAR(20) NOT NULL DEFAULT N'LyThuyet',  -- LyThuyet, ThucHanh, Seminar
    SiSoToiDa       INT NOT NULL,
    SoTietMoiBuoi   INT NOT NULL,               -- do dai 1 buoi hoc (so tiet)
    CanPhongHoc     BIT NOT NULL DEFAULT 1,     -- 0 neu lop khong can gan phong (vd hoc online)
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_LopHocPhan UNIQUE (MaHocPhan, MaHocKy, MaLopCode),
    CONSTRAINT UQ_LopHocPhan_HocKy UNIQUE (MaLopHP, MaHocKy),
    CONSTRAINT CK_LopHocPhan_SiSo CHECK (SiSoToiDa > 0),
    CONSTRAINT CK_LopHocPhan_SoTiet CHECK (SoTietMoiBuoi BETWEEN 1 AND 13)
);

-- Mot nhom hoc phan co the phuc vu nhieu lop hanh chinh (cot "Ten lop" trong mau).
CREATE TABLE LopHanhChinh (
    MaLopHC         INT IDENTITY(1,1) PRIMARY KEY,
    MaHocKy         INT NOT NULL FOREIGN KEY REFERENCES HocKy(MaHocKy),
    TenLop          NVARCHAR(30) NOT NULL,
    CONSTRAINT UQ_LopHanhChinh UNIQUE (MaHocKy, TenLop),
    CONSTRAINT UQ_LopHanhChinh_HocKy UNIQUE (MaLopHC, MaHocKy)
);

CREATE TABLE LopHocPhanLopHanhChinh (
    MaLopHP         INT NOT NULL,
    MaLopHC         INT NOT NULL,
    MaHocKy         INT NOT NULL,
    PRIMARY KEY (MaLopHP, MaLopHC),
    CONSTRAINT FK_LopHP_LopHC_LopHP FOREIGN KEY (MaLopHP, MaHocKy)
        REFERENCES LopHocPhan(MaLopHP, MaHocKy),
    CONSTRAINT FK_LopHP_LopHC_LopHC FOREIGN KEY (MaLopHC, MaHocKy)
        REFERENCES LopHanhChinh(MaLopHC, MaHocKy)
);

-- =====================================================================
-- 3b. CAU HINH TIET HOC (tham khao khung gio Truong Dai hoc Sai Gon)
-- =====================================================================

-- Bang du lieu THAM KHAO, KHONG hardcode cung vao logic - phong dao tao/khoa
-- co the sua truc tiep de khop dung so lieu chinh thuc tung nam hoc/co so.
-- Can cu xac nhan duoc: tiet 1 bat dau 7h00, moi tiet 50 phut, tiet cuoi ca 3
-- ket thuc 20h10 (theo "Thoi gian bieu cac ca hoc" - Khoa Giao duc, Truong
-- Dai hoc Sai Gon). Phan con lai (gio nghi giua tiet/giua ca) la UOC LUONG
-- theo quy uoc pho bien, CAN DOI CHIEU LAI voi so tay sinh vien/phong dao tao
-- chinh thuc truoc khi dung that - sua truc tiep du lieu trong bang nay,
-- khong can sua code.
CREATE TABLE CauHinhTiet (
    MaTiet          INT PRIMARY KEY,        -- 1..13 (danh so lien tuc ca ngay, khong reset theo buoi)
    Buoi            NVARCHAR(10) NOT NULL,  -- 'Sang', 'Chieu', 'Toi'
    ThuTuTrongBuoi  INT NOT NULL,           -- tiet thu may trong buoi do (1..5)
    GioBatDau       TIME NOT NULL,
    GioKetThuc      TIME NOT NULL,
    ThoiLuongPhut   INT NOT NULL DEFAULT 50,
    MucUuTien       INT NOT NULL DEFAULT 1  -- 1 = uu tien xep truoc (Sang/Chieu), 2 = chi xep khi Sang/Chieu khong du cho (Toi)
);

INSERT INTO CauHinhTiet (MaTiet, Buoi, ThuTuTrongBuoi, GioBatDau, GioKetThuc, ThoiLuongPhut, MucUuTien) VALUES
    (1,  N'Sang',  1, '07:00', '07:50', 50, 1),
    (2,  N'Sang',  2, '07:50', '08:40', 50, 1),
    (3,  N'Sang',  3, '08:50', '09:40', 50, 1),   -- nghi giai lao 10 phut sau tiet 2 (uoc luong)
    (4,  N'Sang',  4, '09:40', '10:30', 50, 1),
    (5,  N'Sang',  5, '10:30', '11:20', 50, 1),
    (6,  N'Chieu', 1, '13:00', '13:50', 50, 1),
    (7,  N'Chieu', 2, '13:50', '14:40', 50, 1),
    (8,  N'Chieu', 3, '14:50', '15:40', 50, 1),   -- nghi giai lao 10 phut sau tiet 7 (uoc luong)
    (9,  N'Chieu', 4, '15:40', '16:30', 50, 1),
    (10, N'Chieu', 5, '16:30', '17:20', 50, 1),
    (11, N'Toi',   1, '17:40', '18:30', 50, 2),
    (12, N'Toi',   2, '18:30', '19:20', 50, 2),
    (13, N'Toi',   3, '19:20', '20:10', 50, 2);   -- khop moc "tiet cuoi ca 3 ket thuc 20h10" da xac nhan

-- =====================================================================
-- 4. PHONG HOC
-- =====================================================================

CREATE TABLE ToaNha (
    MaToaNha        INT IDENTITY(1,1) PRIMARY KEY,
    TenToaNha       NVARCHAR(100) NOT NULL
);

CREATE TABLE PhongHoc (
    MaPhong         INT IDENTITY(1,1) PRIMARY KEY,
    MaToaNha        INT NOT NULL FOREIGN KEY REFERENCES ToaNha(MaToaNha),
    MaPhongCode     NVARCHAR(30) NOT NULL UNIQUE, -- vd: 'C.A302', giu nguyen ma SGU
    TenPhong        NVARCHAR(50) NOT NULL,     -- vd: 'B4-201'
    SucChua         INT NOT NULL,
    LoaiPhong       NVARCHAR(30) NOT NULL DEFAULT N'LyThuyet',  -- LyThuyet, ThucHanh, PhongMay
    TrangThai       NVARCHAR(20) NOT NULL DEFAULT N'SanSang',   -- SanSang, BaoTri
    CONSTRAINT UQ_PhongHoc UNIQUE (MaToaNha, TenPhong)
);

-- Khung gio phong khong kha dung (bao tri, da dat truoc cho su kien khac...)
CREATE TABLE PhongKhongKhaDung (
    MaPhongKKD      INT IDENTITY(1,1) PRIMARY KEY,
    MaPhong         INT NOT NULL FOREIGN KEY REFERENCES PhongHoc(MaPhong),
    MaHocKy         INT NOT NULL FOREIGN KEY REFERENCES HocKy(MaHocKy),
    Thu             TINYINT NOT NULL,          -- 2-8 (Thu 2 - Chu Nhat)
    MaTietBatDau    INT NOT NULL FOREIGN KEY REFERENCES CauHinhTiet(MaTiet),
    SoTiet          INT NOT NULL,
    LyDo            NVARCHAR(200) NULL
);

-- =====================================================================
-- 5. CHUYEN MON GIANG VIEN (giao vien nao day duoc hoc phan nao)
-- =====================================================================

CREATE TABLE ChuyenMonGV (
    MaGV            INT NOT NULL FOREIGN KEY REFERENCES GiangVien(MaGV),
    MaHocPhan       INT NOT NULL FOREIGN KEY REFERENCES HocPhan(MaHocPhan),
    MucDoUuTien     TINYINT NOT NULL DEFAULT 2,  -- 1=Chinh, 2=Phu, 3=Co the day khi can
    PRIMARY KEY (MaGV, MaHocPhan)
);

-- =====================================================================
-- 6. NGUYEN VONG GIANG DAY (dung cho rang buoc mem cua thuat toan)
-- =====================================================================

CREATE TABLE NguyenVongGV (
    MaNguyenVong    INT IDENTITY(1,1) PRIMARY KEY,
    MaGV            INT NOT NULL FOREIGN KEY REFERENCES GiangVien(MaGV),
    MaHocKy         INT NOT NULL FOREIGN KEY REFERENCES HocKy(MaHocKy),
    LoaiNguyenVong  NVARCHAR(30) NOT NULL,   -- 'KhungGio', 'NgayNghi', 'KhongDayChungPhong',...
    Thu             TINYINT NULL,             -- ap dung neu LoaiNguyenVong lien quan ngay
    KhungGio        NVARCHAR(20) NULL,        -- 'Sang' / 'Chieu' / 'Toi'
    MucDoUuTien     TINYINT NOT NULL DEFAULT 2,  -- 1=RatThich,2=Thich,3=KhongThich,4=RatKhongThich
    GhiChu          NVARCHAR(200) NULL
);

-- =====================================================================
-- 7. PHAN CONG GIANG DAY (KET QUA THUAT TOAN / THOI KHOA BIEU)
-- =====================================================================

CREATE TABLE PhanCong (
    MaPhanCong      INT IDENTITY(1,1) PRIMARY KEY,
    MaLopHP         INT NOT NULL FOREIGN KEY REFERENCES LopHocPhan(MaLopHP),
    MaGV            INT NULL FOREIGN KEY REFERENCES GiangVien(MaGV),   -- NULL = chua gan
    MaPhong         INT NULL FOREIGN KEY REFERENCES PhongHoc(MaPhong), -- NULL = khong can phong
    DiaDiemKhac     NVARCHAR(100) NULL,        -- dia diem ngoai danh muc phong (vd: thuc tap)
    Thu             TINYINT NOT NULL,          -- 2-8
    MaTietBatDau    INT NOT NULL FOREIGN KEY REFERENCES CauHinhTiet(MaTiet),
    SoTiet          INT NOT NULL,
    NguonGoc        NVARCHAR(20) NOT NULL DEFAULT N'ThuatToan',  -- ThuatToan, ThuCong, DaChinhSua
    TrangThai       NVARCHAR(20) NOT NULL DEFAULT N'ChoDuyet',  -- ChoDuyet, DaDuyet, TuChoi
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME(),
    NgayCapNhat     DATETIME2 NULL,
    CONSTRAINT CK_PhanCong_Thu CHECK (Thu BETWEEN 2 AND 8),
    CONSTRAINT CK_PhanCong_SoTiet CHECK (SoTiet BETWEEN 1 AND 13),
    CONSTRAINT CK_PhanCong_TietKetThuc CHECK (MaTietBatDau + SoTiet - 1 <= 13),
    CONSTRAINT CK_PhanCong_DiaDiem CHECK (MaPhong IS NULL OR DiaDiemKhac IS NULL)
);

-- Tuan hoc la du lieu, khong phai chuoi hien thi. Do dai phu thuoc HocKy.SoTuan.
-- Tang nghiep vu kiem tra Tuan <= HocKy.SoTuan truoc khi ghi trong cung giao dich.
CREATE TABLE PhanCongTuan (
    MaPhanCong      INT NOT NULL FOREIGN KEY REFERENCES PhanCong(MaPhanCong) ON DELETE CASCADE,
    Tuan            TINYINT NOT NULL,
    PRIMARY KEY (MaPhanCong, Tuan),
    CONSTRAINT CK_PhanCongTuan_Tuan CHECK (Tuan BETWEEN 1 AND 53)
);

CREATE INDEX IX_PhanCongTuan_Tuan ON PhanCongTuan(Tuan, MaPhanCong);

GO
CREATE TRIGGER TR_PhanCongTuan_TrongHocKy ON PhanCongTuan
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN PhanCong pc ON pc.MaPhanCong = i.MaPhanCong
        JOIN LopHocPhan lhp ON lhp.MaLopHP = pc.MaLopHP
        JOIN HocKy hk ON hk.MaHocKy = lhp.MaHocKy
        WHERE i.Tuan > hk.SoTuan
    )
        THROW 50001, N'Tuan hoc vuot qua so tuan cua hoc ky.', 1;
END;
GO

CREATE TRIGGER TR_HocKy_GiamSoTuan ON HocKy
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF UPDATE(SoTuan) AND EXISTS (
        SELECT 1
        FROM inserted hk
        JOIN LopHocPhan lhp ON lhp.MaHocKy = hk.MaHocKy
        JOIN PhanCong pc ON pc.MaLopHP = lhp.MaLopHP
        JOIN PhanCongTuan pct ON pct.MaPhanCong = pc.MaPhanCong
        WHERE pct.Tuan > hk.SoTuan
    )
        THROW 50002, N'Khong the giam so tuan khi da co lich hoc vuot gioi han.', 1;
END;
GO

CREATE INDEX IX_PhanCong_GV   ON PhanCong(MaGV, Thu, MaTietBatDau);
CREATE INDEX IX_PhanCong_Phong ON PhanCong(MaPhong, Thu, MaTietBatDau);
CREATE INDEX IX_PhanCong_Lop  ON PhanCong(MaLopHP);

-- =====================================================================
-- 8. TAI KHOAN / PHAN QUYEN
-- =====================================================================

CREATE TABLE TaiKhoan (
    MaTaiKhoan      INT IDENTITY(1,1) PRIMARY KEY,
    TenDangNhap     NVARCHAR(50) NOT NULL UNIQUE,
    MatKhauHash     NVARCHAR(255) NOT NULL,
    VaiTro          NVARCHAR(30) NOT NULL,   -- 'QuanTri', 'TruongBoMon', 'GiangVien'
    MaGV            INT NULL FOREIGN KEY REFERENCES GiangVien(MaGV),  -- chi co neu VaiTro = GiangVien
    TrangThai       NVARCHAR(20) NOT NULL DEFAULT N'HoatDong',
    LanDangNhapCuoi DATETIME2 NULL,
    NgayTao         DATETIME2 DEFAULT SYSUTCDATETIME()
);

-- =====================================================================
-- 9. NHAT KY HE THONG (audit log)
-- =====================================================================

CREATE TABLE NhatKyHeThong (
    MaNhatKy        BIGINT IDENTITY(1,1) PRIMARY KEY,
    MaTaiKhoan      INT NULL FOREIGN KEY REFERENCES TaiKhoan(MaTaiKhoan),
    HanhDong        NVARCHAR(50) NOT NULL,     -- 'TAO_PHAN_CONG', 'SUA_PHAN_CONG', 'DANG_NHAP',...
    DoiTuong        NVARCHAR(50) NULL,         -- ten bang bi tac dong
    MaDoiTuong      INT NULL,
    ChiTiet         NVARCHAR(MAX) NULL,        -- JSON chi tiet thay doi (truoc/sau)
    ThoiGian        DATETIME2 DEFAULT SYSUTCDATETIME()
);

-- =====================================================================
-- 10. LAN CHAY THUAT TOAN (luu lai lich su cac lan chay Stage 1/2 de doi chieu)
-- =====================================================================

CREATE TABLE LanChayThuatToan (
    MaLanChay       INT IDENTITY(1,1) PRIMARY KEY,
    MaHocKy         INT NOT NULL FOREIGN KEY REFERENCES HocKy(MaHocKy),
    ThoiGianBatDau  DATETIME2 NOT NULL,
    ThoiGianKetThuc DATETIME2 NULL,
    TrangThaiStage1 NVARCHAR(20) NULL,    -- OPTIMAL, FEASIBLE, INFEASIBLE
    SoftPenaltyBanDau   FLOAT NULL,
    SoftPenaltyCuoiCung FLOAT NULL,
    SoLanKick       INT NULL,
    ThamSoJSON      NVARCHAR(MAX) NULL,   -- luu STAGE2_CONFIG dung cho lan chay nay
    MaTaiKhoan      INT NULL FOREIGN KEY REFERENCES TaiKhoan(MaTaiKhoan)  -- nguoi khoi chay
);
GO
